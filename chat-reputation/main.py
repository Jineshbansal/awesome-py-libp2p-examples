#!/usr/bin/env python3
"""Decentralized Chat with Peer Reputation - Entry Point."""

import argparse
import logging

import trio

from config import DEFAULT_PORT, DATA_DIR
from chat_client import ChatApp

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Decentralized Chat with Peer Reputation")
    parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
    parser.add_argument("--nick", "-n", default="Anon")
    parser.add_argument("--connect", "-c", help="Peer multiaddr to connect to")
    parser.add_argument("--data-dir", "-d", default=DATA_DIR)
    args = parser.parse_args()
    
    app = ChatApp(args.port, args.nick, args.data_dir)
    
    async def run_app():
        await app.setup()
        await app.run(args.connect)
    
    trio.run(run_app)


if __name__ == "__main__":
    main()