#!/usr/bin/env python

import argparse
import trio
from dht_node import start_dht_node


def main():
    parser = argparse.ArgumentParser(
        description="DHT node with username and optional peer connection"
    )
    parser.add_argument(
        "-u",
        "--username",
        required=True,
        help="Username for this node",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=0,
        help="Port to listen on (0 = auto)",
    )
    parser.add_argument(
        "--connect-peer-id",
        help="PeerID to resolve and connect via DHT",
    )
    parser.add_argument(
        "--bootstrap",
        help="Multiaddr of an existing DHT node",
    )

    args = parser.parse_args()

    try:
        # IMPORTANT: positional args only
        trio.run(
            start_dht_node,
            args.username,
            args.port,
            args.connect_peer_id,
            args.bootstrap,
        )
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")


if __name__ == "__main__":
    main()
