#!/usr/bin/env python3
"""Collaborative Notepad — Entry Point."""

import argparse
import logging

import trio

from config import DEFAULT_LIBP2P_PORT, DEFAULT_WS_BRIDGE_PORT, DEFAULT_DOC_ID, DATA_DIR
from notepad_backend import NotepadBackend

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    parser = argparse.ArgumentParser(
        description="Collaborative Notepad — P2P real-time text editing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Start a peer:
    python main.py --port 8000 --ws-port 8765

  Connect to another peer:
    python main.py --port 8001 --ws-port 8766 \\
        --connect /ip4/127.0.0.1/tcp/8000/ws/p2p/<PEER_ID>

  Custom document ID:
    python main.py --doc-id meeting-notes
        """,
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_LIBP2P_PORT,
        help=f"libp2p WebSocket listen port (default: {DEFAULT_LIBP2P_PORT})",
    )
    parser.add_argument(
        "--ws-port", "-w",
        type=int,
        default=DEFAULT_WS_BRIDGE_PORT,
        help=f"Browser WebSocket bridge port (default: {DEFAULT_WS_BRIDGE_PORT})",
    )
    parser.add_argument(
        "--doc-id", "-d",
        default=DEFAULT_DOC_ID,
        help=f"Document ID to edit (default: {DEFAULT_DOC_ID})",
    )
    parser.add_argument(
        "--data-dir",
        default=DATA_DIR,
        help=f"Data directory for keys and documents (default: {DATA_DIR})",
    )
    parser.add_argument(
        "--connect", "-c",
        help="Multiaddr of a peer to connect to (e.g. /ip4/127.0.0.1/tcp/8000/ws/p2p/<PEER_ID>)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger("notepad").setLevel(logging.DEBUG)
        logging.getLogger("libp2p").setLevel(logging.INFO)

    app = NotepadBackend(
        libp2p_port=args.port,
        ws_bridge_port=args.ws_port,
        doc_id=args.doc_id,
        data_dir=args.data_dir,
    )

    async def run():
        await app.setup()
        await app.run(connect_addr=args.connect)

    try:
        trio.run(run)
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
