"""
runner.py – Interactive shell that boots a hybrid P2P + IPFS federated-learning node.

Usage:
    python runner.py
"""

import os
import sys

# Make sure sibling modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Parent dir for logs.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import multiaddr
import trio
from dotenv import load_dotenv
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.utils.address_validation import find_free_port

from coordinator import COMMANDS, CID_TOPIC, FED_LEARNING_MESH, Node
from logs import setup_logging

load_dotenv()
logger = setup_logging("runner")


async def interactive_shell() -> None:
    # ── Configure role ──
    role = await trio.to_thread.run_sync(
        lambda: input("Role (bootstrap / trainer / client) [bootstrap]: ")
    )
    role = role.strip().lower() or "bootstrap"

    checkpoint_dir = await trio.to_thread.run_sync(
        lambda: input(f"Checkpoint dir [./checkpoints_{role}]: ")
    )
    checkpoint_dir = checkpoint_dir.strip() or f"./checkpoints_{role}"

    node = Node(role=role, checkpoint_dir=checkpoint_dir)
    logger.info(f"Starting as {role.upper()} node")

    # ── Network listen address ──
    ip = "0.0.0.0"
    port = 8000 if role == "bootstrap" else find_free_port()
    listen_addr = multiaddr.Multiaddr(f"/ip4/{ip}/tcp/{port}")

    async with (
        node.host.run(listen_addrs=[listen_addr]),
        trio.open_nursery() as nursery,
    ):
        nursery.start_soon(node.host.get_peerstore().start_cleanup_task, 60)
        logger.debug(f"Listen addr: {node.host.get_addrs()[0]}")

        async with background_trio_service(node.pubsub):
            async with background_trio_service(node.gossipsub):
                await trio.sleep(1)
                await node.pubsub.wait_until_ready()
                logger.info("Pubsub ready")

                # Start background tasks
                nursery.start_soon(node.command_executor, nursery)

                # ── Subscribe to CID announcements topic ──
                cid_sub = await node.pubsub.subscribe(CID_TOPIC)
                nursery.start_soon(node.receive_loop, cid_sub)
                node.subscribed_topics.append(CID_TOPIC)
                logger.info(f"Subscribed to [{CID_TOPIC}] for checkpoint announcements")

                # ── Subscribe to the main federation mesh ──
                main_sub = await node.pubsub.subscribe(FED_LEARNING_MESH)
                nursery.start_soon(node.receive_loop, main_sub)
                node.subscribed_topics.append(FED_LEARNING_MESH)
                logger.info(f"Subscribed to [{FED_LEARNING_MESH}]")

                # ── Connect to bootstrap (non-bootstrap nodes) ──
                if role != "bootstrap":
                    bootstrap_addr = os.getenv("BOOTSTRAP_ADDR")
                    if bootstrap_addr:
                        maddr = multiaddr.Multiaddr(bootstrap_addr)
                        info = info_from_p2p_addr(maddr)
                        node.bootstrap_addr = info.addrs[0]
                        node.bootstrap_id = info.peer_id
                        await node.host.connect(info)
                        logger.info("Connected to BOOTSTRAP node")
                    else:
                        logger.warning("BOOTSTRAP_ADDR not set – running standalone")

                # ── Offline-sync: try loading the latest local checkpoint ──
                node._load_local()
                if node.current_weights is not None:
                    logger.info(
                        f"Resumed from local checkpoint round {node.current_round}"
                    )

                await trio.sleep(1)
                logger.info("Interactive mode ready. Type 'help' for commands.")
                logger.info(COMMANDS)

                # ── REPL ──
                while not node.termination_event.is_set():
                    try:
                        user_input = await trio.to_thread.run_sync(
                            lambda: input("Command> ")
                        )
                        if not user_input.strip():
                            continue
                        parts = user_input.strip().split(" ", 2)
                        await node.send_channel.send(parts)
                    except EOFError:
                        break
                    except Exception as e:
                        logger.error(f"Shell error: {e}")
                        await trio.sleep(0.5)

    logger.info("Shutdown complete. Goodbye!")


if __name__ == "__main__":
    try:
        trio.run(interactive_shell)
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except BaseException as e:
        logger.critical(f"Fatal: {e}")
