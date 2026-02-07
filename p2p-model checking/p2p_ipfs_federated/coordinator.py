"""
coordinator.py – Hybrid P2P + IPFS federated-learning coordinator.

Extends the original libp2p-only coordinator with:
  • IPFS checkpoint upload / download
  • CID sharing over pubsub
  • Local persistence (save / load model states)
  • Offline-peer sync via IPFS fallback
"""

import ast
import json
import os
import pickle
import random
import time
from pathlib import Path

import multiaddr
import trio
from dotenv import load_dotenv
from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.stream_muxer.mplex.mplex import MPLEX_PROTOCOL_ID, Mplex
from libp2p.utils.address_validation import find_free_port

from ipfs_utils import IPFSClient
from persistence import CheckpointStore
from logs import setup_logging

load_dotenv()
logger = setup_logging("coordinator")

GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")
FED_LEARNING_MESH = "fed-learn"
CID_TOPIC = "model-cids"          # dedicated pubsub topic for CID announcements
PUBLIC_IP = os.getenv("IP", "127.0.0.1")
IS_CLOUD = os.getenv("IS_CLOUD", "False")

COMMANDS = """
Available commands:
  connect <multiaddr>              Connect to another peer
  advertize <topic>                Start a training round (CLIENT only)
  train <topic> <dataset> <model>  Kick off training
  join <topic>                     Join a training mesh (TRAINER only)
  leave <topic>                    Leave a mesh
  publish <topic> <message>        Publish arbitrary message

  checkpoint_save <round>          Save current weights locally + upload to IPFS
  checkpoint_load [round]          Load weights from local disk (latest if omitted)
  checkpoint_fetch <cid>           Download a checkpoint from IPFS by CID
  sync                             Fetch the latest model from IPFS (offline-sync)
  cids                             Show known IPFS CIDs for model checkpoints
  rounds                           List locally stored checkpoint rounds

  topics                           List subscribed topics
  peers                            List connected peers
  local                            Show local multiaddr
  help                             This help text
  exit                             Shut down
"""


class Node:
    """
    Peer node that combines libp2p pubsub with IPFS checkpoint storage.
    """

    def __init__(self, role: str, checkpoint_dir: str = "./checkpoints"):
        # ── libp2p ──
        self.host = new_host(muxer_opt={MPLEX_PROTOCOL_ID: Mplex})
        self.gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=10,
            degree_low=6,
            degree_high=14,
            time_to_live=60,
            gossip_window=3,
            gossip_history=5,
            heartbeat_initial_delay=2.0,
            heartbeat_interval=5,
        )
        self.pubsub = Pubsub(self.host, self.gossipsub)
        self.termination_event = trio.Event()

        # ── IPFS + persistence ──
        self.ipfs = IPFSClient()
        self.checkpoint_store = CheckpointStore(base_dir=checkpoint_dir)

        # Track CIDs announced over the network  {round_num: cid}
        self.known_cids: dict[int, str] = {}
        self.current_round: int = 0
        self.current_weights = None

        # ── role / mesh bookkeeping ──
        self.role = role
        self.bootstrap_addr = None
        self.bootstrap_id = None
        self.is_subscribed = False
        self.training_topic = None
        self.subscribed_topics: list[str] = []
        self.connected_nodes: set[str] = set()

        # ── trio channels ──
        self.send_channel, self.receive_channel = trio.open_memory_channel(100)

    # ──────────────────────────────────────────────────────────────────────
    # Command executor  (runs in its own task)
    # ──────────────────────────────────────────────────────────────────────

    async def command_executor(self, nursery):
        logger.warning("Starting command executor loop")

        async with self.receive_channel:
            async for parts in self.receive_channel:
                try:
                    if not parts:
                        continue
                    cmd = parts[0].lower()

                    # ── Networking ──────────────────────────────────────
                    if cmd == "connect" and len(parts) > 1:
                        maddr = multiaddr.Multiaddr(parts[1])
                        info = info_from_p2p_addr(maddr)
                        await self.host.connect(info)
                        logger.info(f"Connected to {info.peer_id}")

                    elif cmd == "advertize" and len(parts) > 1:
                        topic = parts[1]
                        sub = await self.pubsub.subscribe(topic)
                        nursery.start_soon(self.receive_loop, sub)
                        self.subscribed_topics.append(topic)
                        self.training_topic = topic
                        self.is_subscribed = True
                        await self.pubsub.publish(
                            FED_LEARNING_MESH,
                            f"Training round starting in [{topic}]".encode(),
                        )

                    elif cmd == "join" and len(parts) > 1:
                        topic = parts[1]
                        sub = await self.pubsub.subscribe(topic)
                        nursery.start_soon(self.receive_loop, sub)
                        self.subscribed_topics.append(topic)
                        self.training_topic = topic
                        self.is_subscribed = True
                        await self.pubsub.publish(topic, b"Joined as TRAINER")

                    elif cmd == "leave" and len(parts) > 1:
                        topic = parts[1]
                        await self.pubsub.unsubscribe(topic)
                        if topic in self.subscribed_topics:
                            self.subscribed_topics.remove(topic)
                        self.is_subscribed = False
                        self.training_topic = None
                        logger.info(f"Left [{topic}]")

                    elif cmd == "publish" and len(parts) > 2:
                        await self.pubsub.publish(parts[1], parts[2].encode())

                    # ── Checkpoint / IPFS commands ──────────────────────
                    elif cmd == "checkpoint_save":
                        round_num = int(parts[1]) if len(parts) > 1 else self.current_round
                        await self._save_and_upload(round_num)

                    elif cmd == "checkpoint_load":
                        round_num = int(parts[1]) if len(parts) > 1 else None
                        self._load_local(round_num)

                    elif cmd == "checkpoint_fetch" and len(parts) > 1:
                        cid = parts[1]
                        round_num = int(parts[2]) if len(parts) > 2 else self.current_round + 1
                        await self._fetch_from_ipfs(cid, round_num)

                    elif cmd == "sync":
                        await self._sync_from_ipfs()

                    elif cmd == "cids":
                        logger.info(f"Known CIDs: {json.dumps(self.known_cids, indent=2)}")

                    elif cmd == "rounds":
                        logger.info(f"Local rounds: {self.checkpoint_store.list_rounds()}")

                    # ── Info commands ──────────────────────────────────
                    elif cmd == "topics":
                        logger.info(f"Subscribed: {self.subscribed_topics}")

                    elif cmd == "peers":
                        peers = set(self.pubsub.peers.keys())
                        logger.info(f"Connected peers: {[str(p) for p in peers]}")

                    elif cmd == "local":
                        addrs = self.host.get_addrs()
                        logger.info(f"Local addrs: {[str(a) for a in addrs]}")
                        logger.info(f"Peer ID: {self.host.get_id()}")

                    elif cmd == "help":
                        logger.info(COMMANDS)

                    elif cmd == "exit":
                        logger.warning("Shutting down…")
                        self.termination_event.set()
                        nursery.cancel_scope.cancel()

                    # ── Internal CID announcement (from pubsub) ────────
                    elif cmd == "_cid_announce":
                        # parts: ["_cid_announce", round_str, cid]
                        r = int(parts[1])
                        c = parts[2]
                        self.known_cids[r] = c
                        logger.info(f"Received CID for round {r}: {c}")

                except Exception as e:
                    logger.error(f"Error executing command {parts}: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # Pubsub receive loop
    # ──────────────────────────────────────────────────────────────────────

    async def receive_loop(self, subscription):
        logger.warning("Starting receive loop")
        try:
            while not self.termination_event.is_set():
                try:
                    msg = await subscription.get()
                    if msg is None:
                        break

                    sender = msg.from_id
                    if isinstance(sender, bytes):
                        from libp2p.peer.id import ID as PeerID
                        sender_id = PeerID(sender)
                        sender_str = str(sender_id)
                    else:
                        sender_str = str(sender)

                    # Ignore own messages
                    if str(self.host.get_id()) == sender_str:
                        continue

                    try:
                        decoded: str = msg.data.decode("utf-8")
                    except UnicodeDecodeError:
                        logger.debug(f"Skipping non-UTF-8 message from {sender_str[:12]}…")
                        continue

                    # ── CID announcement ──
                    if decoded.startswith("CID:"):
                        # Format: "CID:<round>:<cid>"
                        _, round_str, cid = decoded.split(":", 2)
                        await self.send_channel.send(["_cid_announce", round_str, cid])
                        continue

                    # ── Normal message ──
                    logger.info(f"[{sender_str[:12]}…] {decoded}")

                except trio.EndOfChannel:
                    break
                except Exception as e:
                    logger.error(f"Receive loop error: {e}")
                    await trio.sleep(0.5)
        finally:
            logger.info("Receive loop terminated")

    # ──────────────────────────────────────────────────────────────────────
    # IPFS + Persistence helpers
    # ──────────────────────────────────────────────────────────────────────

    async def _save_and_upload(self, round_num: int):
        """Save current weights locally, upload to IPFS, broadcast CID."""
        if self.current_weights is None:
            logger.warning("No weights in memory to save")
            return

        # 1. Save locally
        self.checkpoint_store.save_checkpoint(
            weights=self.current_weights,
            round_num=round_num,
            peer_id=str(self.host.get_id()),
        )

        # 2. Upload to IPFS
        data = pickle.dumps(self.current_weights)
        try:
            cid = await trio.to_thread.run_sync(
                lambda: self.ipfs.upload_bytes(data, filename=f"round_{round_num:04d}.pkl")
            )
        except Exception as e:
            logger.error(f"IPFS upload failed: {e}")
            return

        # 3. Update local metadata with CID
        self.known_cids[round_num] = cid
        meta = self.checkpoint_store.load_metadata(round_num) or {}
        meta["cid"] = cid
        meta_path = self.checkpoint_store.base_dir / f"round_{round_num:04d}" / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        # 4. Announce CID on the dedicated topic
        announcement = f"CID:{round_num}:{cid}"
        try:
            await self.pubsub.publish(CID_TOPIC, announcement.encode())
            logger.info(f"Announced CID for round {round_num}: {cid}")
        except Exception as e:
            logger.warning(f"Could not broadcast CID (no peers?): {e}")

        self.current_round = round_num

    def _load_local(self, round_num: int | None = None):
        """Load weights from local disk."""
        weights, meta = self.checkpoint_store.load_checkpoint(round_num)
        if weights is not None:
            self.current_weights = weights
            if meta:
                self.current_round = meta.get("round", self.current_round)
                if meta.get("cid"):
                    self.known_cids[self.current_round] = meta["cid"]
            logger.info(f"Loaded round {self.current_round} from disk")
        else:
            logger.warning("No local checkpoint found")

    async def _fetch_from_ipfs(self, cid: str, round_num: int):
        """Download a checkpoint from IPFS by CID and load into memory."""
        try:
            raw = await trio.to_thread.run_sync(lambda: self.ipfs.download_bytes(cid))
            weights = pickle.loads(raw)
            self.current_weights = weights
            self.current_round = round_num
            self.known_cids[round_num] = cid

            # Also persist locally
            self.checkpoint_store.save_checkpoint(
                weights=weights,
                round_num=round_num,
                peer_id=str(self.host.get_id()),
                cid=cid,
            )
            logger.info(f"Fetched + saved round {round_num} from IPFS (CID: {cid})")
        except Exception as e:
            logger.error(f"IPFS fetch failed: {e}")

    async def _sync_from_ipfs(self):
        """
        Offline-sync: find the highest known CID and fetch it.
        If no CIDs are known yet, try to load the latest local checkpoint.
        """
        if self.known_cids:
            latest_round = max(self.known_cids)
            cid = self.known_cids[latest_round]
            logger.info(f"Syncing to round {latest_round} via IPFS…")
            await self._fetch_from_ipfs(cid, latest_round)
        else:
            # Fallback: try local
            self._load_local()
            if self.current_weights is None:
                logger.warning("No CIDs known and no local checkpoints – nothing to sync")

    # ──────────────────────────────────────────────────────────────────────
    # Public helpers for programmatic use (e.g. from tests)
    # ──────────────────────────────────────────────────────────────────────

    def set_weights(self, weights, round_num: int | None = None):
        """Manually set the current in-memory weights."""
        self.current_weights = weights
        if round_num is not None:
            self.current_round = round_num
