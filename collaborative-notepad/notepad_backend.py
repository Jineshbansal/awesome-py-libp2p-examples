"""
Collaborative Notepad — py-libp2p backend peer.

Runs a libp2p host that:
1. Listens on WebSocket for peer-to-peer communication (GossipSub)
2. Runs a plain WebSocket bridge for browser clients
3. Translates browser ops ↔ GossipSub messages
4. Persists document state to SQLite
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import trio
from multiaddr import Multiaddr
from trio_websocket import (
    ConnectionClosed,
    serve_websocket,
    WebSocketConnection,
)

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.tools.async_service.trio_service import background_trio_service

from config import (
    DEFAULT_LIBP2P_PORT,
    DEFAULT_WS_BRIDGE_PORT,
    GOSSIPSUB_PROTOCOL_ID,
    GOSSIPSUB_DEGREE,
    GOSSIPSUB_DEGREE_LOW,
    GOSSIPSUB_DEGREE_HIGH,
    GOSSIPSUB_HEARTBEAT_INTERVAL,
    GOSSIPSUB_HEARTBEAT_INITIAL_DELAY,
    GOSSIPSUB_TIME_TO_LIVE,
    GOSSIPSUB_GOSSIP_WINDOW,
    GOSSIPSUB_GOSSIP_HISTORY,
    SYNC_PROTOCOL_ID,
    TOPIC_PREFIX,
    MSG_INSERT,
    MSG_DELETE,
    MSG_FULL_STATE,
    MSG_SYNC_REQUEST,
    MSG_SYNC_RESPONSE,
    MSG_CURSOR,
    MSG_PEER_JOIN,
    MSG_PEER_LEAVE,
)
from crdt import Op, TextCRDT
from document_store import DocumentStore

logger = logging.getLogger("notepad")


# ---------------------------------------------------------------------------
# Key persistence (same pattern as chat-reputation)
# ---------------------------------------------------------------------------

def load_or_create_key(data_dir: str, port: int):
    """Load an existing key pair or create a new one.

    Ensures the same peer ID is used across restarts.
    """
    key_file = Path(data_dir) / f"peer_key_{port}.json"
    key_file.parent.mkdir(parents=True, exist_ok=True)

    if key_file.exists():
        try:
            with open(key_file) as f:
                data = json.load(f)
            secret = bytes.fromhex(data["private_key"])
            return create_new_key_pair(secret)
        except Exception as e:
            logger.warning(f"Could not load key: {e}, creating new one")

    key_pair = create_new_key_pair()
    with open(key_file, "w") as f:
        json.dump({"private_key": key_pair.private_key.to_bytes().hex()}, f)
    return key_pair


# ---------------------------------------------------------------------------
# Notepad Backend
# ---------------------------------------------------------------------------

class NotepadBackend:
    """Main application: libp2p host + WS bridge + CRDT + persistence."""

    def __init__(
        self,
        libp2p_port: int = DEFAULT_LIBP2P_PORT,
        ws_bridge_port: int = DEFAULT_WS_BRIDGE_PORT,
        doc_id: str = "default",
        data_dir: str = "./notepad_data",
    ):
        self.libp2p_port = libp2p_port
        self.ws_bridge_port = ws_bridge_port
        self.doc_id = doc_id
        self.data_dir = data_dir
        self.topic = f"{TOPIC_PREFIX}{doc_id}"

        # Will be set in setup()
        self.host = None
        self.gossipsub = None
        self.pubsub = None
        self.crdt: TextCRDT | None = None
        self.store: DocumentStore | None = None
        self.peer_id_str: str = ""

        # Browser clients connected via the WS bridge
        self.browser_clients: set[WebSocketConnection] = set()

    # --- Setup ----------------------------------------------------------

    async def setup(self) -> None:
        """Initialize the libp2p host, GossipSub, CRDT, and document store."""
        # 1. Key pair (persistent identity)
        key_pair = load_or_create_key(self.data_dir, self.libp2p_port)

        # 2. Create libp2p host listening on WebSocket
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{self.libp2p_port}/ws")
        self.host = new_host(key_pair=key_pair, listen_addrs=[listen_addr])
        self.peer_id_str = str(self.host.get_id())

        # 3. GossipSub router
        self.gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=GOSSIPSUB_DEGREE,
            degree_low=GOSSIPSUB_DEGREE_LOW,
            degree_high=GOSSIPSUB_DEGREE_HIGH,
            time_to_live=GOSSIPSUB_TIME_TO_LIVE,
            gossip_window=GOSSIPSUB_GOSSIP_WINDOW,
            gossip_history=GOSSIPSUB_GOSSIP_HISTORY,
            heartbeat_initial_delay=GOSSIPSUB_HEARTBEAT_INITIAL_DELAY,
            heartbeat_interval=GOSSIPSUB_HEARTBEAT_INTERVAL,
        )

        # 4. PubSub layer
        self.pubsub = Pubsub(
            self.host,
            self.gossipsub,
            strict_signing=False,  # Simplified for demo — no signing overhead
        )

        # 5. Document store + CRDT
        self.store = DocumentStore(Path(self.data_dir) / "documents.db")
        existing = self.store.load_state(self.doc_id, self.peer_id_str)
        if existing is not None:
            self.crdt = existing
            logger.info(
                f"Loaded document '{self.doc_id}' from disk "
                f"({len(self.crdt)} chars)"
            )
        else:
            self.crdt = TextCRDT(self.peer_id_str)
            logger.info(f"Created new document '{self.doc_id}'")

        # 6. Register the sync stream handler (for state catch-up)
        self.host.set_stream_handler(SYNC_PROTOCOL_ID, self._handle_sync_stream)

    # --- Sync stream (peer-to-peer state catch-up) ----------------------

    async def _handle_sync_stream(self, stream) -> None:
        """Handle a /notepad/sync/1.0.0 stream from another peer.

        Protocol:
        - Requester sends: {"type": "SYNC_REQUEST", "since": <timestamp>}
        - We respond with FULL_STATE or ops since timestamp.
        """
        try:
            data = await stream.read(4096)
            if not data:
                await stream.close()
                return

            msg = json.loads(data.decode("utf-8"))
            msg_type = msg.get("type")

            if msg_type == MSG_SYNC_REQUEST:
                # Send full CRDT state
                state = self.crdt.get_state()
                response = json.dumps({
                    "type": MSG_FULL_STATE,
                    "doc_id": self.doc_id,
                    "state": state,
                })
                await stream.write(response.encode("utf-8"))

            await stream.close()
        except Exception as e:
            logger.error(f"Sync stream error: {e}")
            try:
                await stream.close()
            except Exception:
                pass

    async def request_sync(self, peer_id: ID) -> None:
        """Request full state from a peer via the sync protocol."""
        try:
            stream = await self.host.new_stream(peer_id, [SYNC_PROTOCOL_ID])
            request = json.dumps({"type": MSG_SYNC_REQUEST, "since": 0})
            await stream.write(request.encode("utf-8"))

            data = await stream.read(65536)
            if data:
                msg = json.loads(data.decode("utf-8"))
                if msg.get("type") == MSG_FULL_STATE:
                    state = msg["state"]
                    self.crdt.load_state(state)
                    self.store.save_state(self.doc_id, self.crdt)
                    logger.info(
                        f"Synced document from peer — "
                        f"{len(self.crdt)} chars"
                    )
                    # Push updated state to all browser clients
                    await self._broadcast_to_browsers({
                        "type": MSG_FULL_STATE,
                        "text": self.crdt.to_plaintext(),
                    })

            await stream.close()
        except Exception as e:
            logger.error(f"Sync request failed: {e}")

    # --- GossipSub message handler --------------------------------------

    async def _handle_pubsub_messages(self, subscription) -> None:
        """Process incoming GossipSub messages from other peers."""
        while True:
            try:
                msg = await subscription.get()

                # Decode the pubsub message data
                raw = msg.data.decode("utf-8")
                payload = json.loads(raw)
                msg_type = payload.get("type")

                # Ignore messages from ourselves
                sender = msg.from_id
                sender_str = str(ID(sender)) if isinstance(sender, bytes) else str(sender)
                if sender_str == self.peer_id_str:
                    continue

                if msg_type in (MSG_INSERT, MSG_DELETE):
                    op = Op.from_dict(payload["op"])
                    applied = self.crdt.apply_remote_op(op)
                    if applied:
                        self.store.store_op(self.doc_id, op)
                        self.store.save_state(self.doc_id, self.crdt)

                        # Forward to browser clients
                        await self._broadcast_to_browsers({
                            "type": msg_type,
                            "op": payload["op"],
                            "text": self.crdt.to_plaintext(),
                        })

                elif msg_type == MSG_CURSOR:
                    # Forward cursor positions to browsers as-is
                    await self._broadcast_to_browsers(payload)

                elif msg_type == MSG_PEER_JOIN:
                    await self._broadcast_to_browsers(payload)

            except Exception as e:
                logger.error(f"PubSub message error: {e}")

    # --- Browser WebSocket bridge ---------------------------------------

    async def _handle_browser_ws(self, ws: WebSocketConnection) -> None:
        """Handle a single browser client WebSocket connection."""
        self.browser_clients.add(ws)
        client_id = f"browser-{id(ws) % 10000:04d}"
        logger.info(f"Browser client connected: {client_id}")

        try:
            # Send current document state
            welcome = json.dumps({
                "type": MSG_FULL_STATE,
                "text": self.crdt.to_plaintext(),
                "doc_id": self.doc_id,
                "peer_id": self.peer_id_str,
                "peer_count": len(self.browser_clients),
            })
            await ws.send_message(welcome)

            # Notify others
            await self._publish_to_gossipsub({
                "type": MSG_PEER_JOIN,
                "peer_id": self.peer_id_str,
                "client_id": client_id,
            })
            await self._broadcast_to_browsers({
                "type": "PEER_COUNT",
                "count": len(self.browser_clients),
            }, exclude=ws)

            # Process messages from this browser
            while True:
                raw = await ws.get_message()
                await self._process_browser_message(raw, client_id, ws)

        except ConnectionClosed:
            logger.info(f"Browser client disconnected: {client_id}")
        except Exception as e:
            logger.error(f"Browser WS error ({client_id}): {e}")
        finally:
            self.browser_clients.discard(ws)
            await self._broadcast_to_browsers({
                "type": "PEER_COUNT",
                "count": len(self.browser_clients),
            })
            await self._publish_to_gossipsub({
                "type": MSG_PEER_LEAVE,
                "peer_id": self.peer_id_str,
                "client_id": client_id,
            })

    async def _process_browser_message(
        self, raw: str, client_id: str, sender_ws: WebSocketConnection
    ) -> None:
        """Process a message received from a browser client."""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from {client_id}")
            return

        msg_type = payload.get("type")

        if msg_type == MSG_INSERT:
            position = payload["position"]
            char = payload["char"]
            op = self.crdt.local_insert(position, char)
            self.store.store_op(self.doc_id, op)
            self.store.save_state(self.doc_id, self.crdt)

            # Broadcast via GossipSub (to other backend peers)
            await self._publish_to_gossipsub({
                "type": MSG_INSERT,
                "op": op.to_dict(),
            })
            # Broadcast to other browser clients on THIS backend
            await self._broadcast_to_browsers({
                "type": MSG_INSERT,
                "op": op.to_dict(),
                "text": self.crdt.to_plaintext(),
            }, exclude=sender_ws)

        elif msg_type == MSG_DELETE:
            position = payload["position"]
            op = self.crdt.local_delete(position)
            if op:
                self.store.store_op(self.doc_id, op)
                self.store.save_state(self.doc_id, self.crdt)

                await self._publish_to_gossipsub({
                    "type": MSG_DELETE,
                    "op": op.to_dict(),
                })
                await self._broadcast_to_browsers({
                    "type": MSG_DELETE,
                    "op": op.to_dict(),
                    "text": self.crdt.to_plaintext(),
                }, exclude=sender_ws)

        elif msg_type == "BATCH":
            # Handle a batch of insert/delete ops from a single keystroke diff
            ops_data = payload.get("ops", [])
            for op_data in ops_data:
                op_type = op_data.get("type")
                if op_type == MSG_INSERT:
                    op = self.crdt.local_insert(op_data["position"], op_data["char"])
                    self.store.store_op(self.doc_id, op)
                    await self._publish_to_gossipsub({
                        "type": MSG_INSERT,
                        "op": op.to_dict(),
                    })
                elif op_type == MSG_DELETE:
                    op = self.crdt.local_delete(op_data["position"])
                    if op:
                        self.store.store_op(self.doc_id, op)
                        await self._publish_to_gossipsub({
                            "type": MSG_DELETE,
                            "op": op.to_dict(),
                        })

            self.store.save_state(self.doc_id, self.crdt)

            # Send updated text to all browsers (including sender for consistency)
            await self._broadcast_to_browsers({
                "type": MSG_FULL_STATE,
                "text": self.crdt.to_plaintext(),
            }, exclude=sender_ws)

        elif msg_type == MSG_CURSOR:
            payload["client_id"] = client_id
            await self._publish_to_gossipsub(payload)
            await self._broadcast_to_browsers(payload, exclude=sender_ws)

        elif msg_type == MSG_SYNC_REQUEST:
            # Browser requesting full state
            await sender_ws.send_message(json.dumps({
                "type": MSG_FULL_STATE,
                "text": self.crdt.to_plaintext(),
                "doc_id": self.doc_id,
            }))

    # --- Helpers --------------------------------------------------------

    async def _publish_to_gossipsub(self, payload: dict) -> None:
        """Publish a JSON message to the GossipSub topic."""
        try:
            data = json.dumps(payload).encode("utf-8")
            await self.pubsub.publish(self.topic, data)
        except Exception as e:
            logger.error(f"GossipSub publish error: {e}")

    async def _broadcast_to_browsers(
        self, payload: dict, exclude: WebSocketConnection | None = None
    ) -> None:
        """Send a JSON message to all connected browser clients."""
        message = json.dumps(payload)
        dead: list[WebSocketConnection] = []
        for ws in self.browser_clients:
            if ws is exclude:
                continue
            try:
                await ws.send_message(message)
            except (ConnectionClosed, Exception):
                dead.append(ws)
        for ws in dead:
            self.browser_clients.discard(ws)

    # --- Main run loop --------------------------------------------------

    async def run(self, connect_addr: str | None = None) -> None:
        """Start the backend: libp2p host, GossipSub, WS bridge, CLI."""
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{self.libp2p_port}/ws")

        async with self.host.run(listen_addrs=[listen_addr]):
            async with background_trio_service(self.pubsub):
                # Print startup info
                host_addr = (
                    f"/ip4/127.0.0.1/tcp/{self.libp2p_port}"
                    f"/ws/p2p/{self.host.get_id()}"
                )
                print()
                print("=" * 60)
                print("  Collaborative Notepad — P2P Backend")
                print("=" * 60)
                print(f"  Document : {self.doc_id}")
                print(f"  Peer ID  : {self.host.get_id()}")
                print(f"  libp2p   : ws://0.0.0.0:{self.libp2p_port}")
                print(f"  Browser  : ws://localhost:{self.ws_bridge_port}")
                print(f"  Connect  : {host_addr}")
                print()
                print("  Open static/index.html in your browser,")
                print(f"  then connect to ws://localhost:{self.ws_bridge_port}")
                print()
                print("  Commands: /status /doc /peers /quit")
                print("=" * 60)
                print()

                # Connect to another peer if requested
                if connect_addr:
                    try:
                        info = info_from_p2p_addr(Multiaddr(connect_addr))
                        await self.host.connect(info)
                        print(f"Connected to peer: {info.peer_id}")
                        await trio.sleep(1)
                        # Sync document state from the peer
                        await self.request_sync(info.peer_id)
                    except Exception as e:
                        print(f"Connection failed: {e}")

                # Subscribe to the document topic
                subscription = await self.pubsub.subscribe(self.topic)

                async with trio.open_nursery() as nursery:
                    # Task 1: GossipSub message handler
                    nursery.start_soon(self._handle_pubsub_messages, subscription)
                    # Task 2: WS bridge for browsers
                    nursery.start_soon(self._run_ws_bridge)
                    # Task 3: CLI input
                    nursery.start_soon(self._cli_loop, nursery)

    async def _run_ws_bridge(self) -> None:
        """Run the plain WebSocket server for browser clients."""
        logger.info(f"WS bridge listening on port {self.ws_bridge_port}")
        await serve_websocket(
            self._handle_browser_ws,
            "0.0.0.0",
            self.ws_bridge_port,
            ssl_context=None,
        )

    async def _cli_loop(self, nursery: trio.Nursery) -> None:
        """Handle CLI commands from stdin."""
        while True:
            try:
                user_input = await trio.to_thread.run_sync(input)
                cmd = user_input.strip().lower()

                if cmd == "/quit":
                    print("Shutting down...")
                    self.store.save_state(self.doc_id, self.crdt)
                    nursery.cancel_scope.cancel()
                    break
                elif cmd == "/status":
                    self._print_status()
                elif cmd == "/doc":
                    text = self.crdt.to_plaintext()
                    print(f"\n--- Document '{self.doc_id}' ({len(self.crdt)} chars) ---")
                    print(text if text else "(empty)")
                    print("--- end ---\n")
                elif cmd == "/peers":
                    peers = list(self.host.get_network().connections.keys())
                    print(f"\nConnected libp2p peers: {len(peers)}")
                    for p in peers:
                        print(f"  • {p}")
                    print(f"Browser clients: {len(self.browser_clients)}\n")
                elif cmd.startswith("/connect "):
                    addr = cmd.split(" ", 1)[1]
                    try:
                        info = info_from_p2p_addr(Multiaddr(addr))
                        await self.host.connect(info)
                        print(f"Connected to: {info.peer_id}")
                        await trio.sleep(0.5)
                        await self.request_sync(info.peer_id)
                    except Exception as e:
                        print(f"Connection failed: {e}")
                elif user_input.strip():
                    print("Commands: /status /doc /peers /connect <addr> /quit")

            except (KeyboardInterrupt, EOFError):
                self.store.save_state(self.doc_id, self.crdt)
                nursery.cancel_scope.cancel()
                break

    def _print_status(self) -> None:
        peers = list(self.host.get_network().connections.keys())
        mesh = list(self.gossipsub.mesh.get(self.topic, set()))
        print()
        print(f"  [STATUS] {'━' * 44}")
        print(f"  Document : {self.doc_id} ({len(self.crdt)} chars)")
        print(f"  Peer ID  : {self.host.get_id()}")
        print(f"  libp2p   : {len(peers)} peers connected")
        print(f"  Mesh     : {len(mesh)} peers in topic mesh")
        print(f"  Browsers : {len(self.browser_clients)} clients")
        print(f"  Ops      : {self.store.get_op_count(self.doc_id)} stored")
        print(f"  {'━' * 50}")
        print()
