"""Main entry point for the collaborative whiteboard."""

import argparse
import logging
import signal
import sys

import trio
from multiaddr import Multiaddr
from libp2p.tools.async_service.trio_service import background_trio_service

from node import WhiteboardNode
from whiteboard_crdt import WhiteboardCRDT
from sync_protocol import SyncProtocol
from ws_bridge import WebSocketBridge
from config import (
    DEFAULT_LIBP2P_PORT,
    DEFAULT_WS_BRIDGE_PORT,
    DEFAULT_BOARD_ID
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def run_app(
    libp2p_port: int,
    ws_port: int,
    board_id: str,
    bootstrap_peers: list = None
):
    """Run the collaborative whiteboard application under Trio."""
    logger.info("Starting Collaborative Whiteboard...")

    node = WhiteboardNode(port=libp2p_port)
    node.setup()

    listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{libp2p_port}")

    async with node.host.run(listen_addrs=[listen_addr]):
        async with background_trio_service(node.pubsub):
            await node.pubsub.wait_until_ready()

            peer_id = node.get_peer_id()

            whiteboard = WhiteboardCRDT(
                board_id=board_id,
                peer_id=str(peer_id)
            )

            sync_protocol = SyncProtocol(
                node=node,
                whiteboard=whiteboard,
                board_id=board_id
            )

            ws_bridge = WebSocketBridge(
                whiteboard=whiteboard,
                sync_protocol=sync_protocol,
                port=ws_port
            )

            async with trio.open_nursery() as nursery:
                await sync_protocol.start(nursery)
                await ws_bridge.start(nursery)

                if bootstrap_peers:
                    for peer_addr in bootstrap_peers:
                        try:
                            await node.connect_to_peer(peer_addr)
                        except Exception as e:
                            logger.error(f"Failed to connect to peer {peer_addr}: {e}")

                addrs = node.get_addrs()
                logger.info("=" * 60)
                logger.info("Collaborative Whiteboard Started!")
                logger.info(f"Peer ID: {peer_id}")
                logger.info(f"Board ID: {board_id}")
                logger.info(f"Addresses: {addrs}")
                logger.info(f"WebSocket URL: ws://localhost:{ws_port}")
                logger.info("=" * 60)

                # Run until cancelled
                try:
                    await trio.sleep_forever()
                except trio.Cancelled:
                    logger.info("Shutting down...")
                    await sync_protocol.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Collaborative Whiteboard - P2P synchronized drawing"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_LIBP2P_PORT,
        help=f"libp2p port (default: {DEFAULT_LIBP2P_PORT})"
    )
    parser.add_argument(
        "--ws-port", "-w",
        type=int,
        default=DEFAULT_WS_BRIDGE_PORT,
        help=f"WebSocket bridge port (default: {DEFAULT_WS_BRIDGE_PORT})"
    )
    parser.add_argument(
        "--board", "-b",
        type=str,
        default=DEFAULT_BOARD_ID,
        help=f"Board ID (default: {DEFAULT_BOARD_ID})"
    )
    parser.add_argument(
        "--peer", "-c",
        type=str,
        action="append",
        dest="peers",
        help="Bootstrap peer multiaddr (can be specified multiple times)"
    )

    args = parser.parse_args()

    try:
        trio.run(
            run_app,
            args.port,
            args.ws_port,
            args.board,
            args.peers
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()