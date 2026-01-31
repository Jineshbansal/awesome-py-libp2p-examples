#!/usr/bin/env python3
"""
Decentralized Chat with Peer Reputation

Entry point for the reputation-based decentralized chat application.
"""

import argparse
import logging

import trio

from chat_client import ChatClient
from config import DEFAULT_PORT, DEFAULT_DATA_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)


async def main():
    parser = argparse.ArgumentParser(description="Decentralized Chat with Peer Reputation")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--nick", default="Anonymous", help="Your nickname")
    parser.add_argument("--connect", help="Multiaddr of peer to connect to")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Directory for storing reputation data")
    
    args = parser.parse_args()
    
    # Create and run chat client
    chat = ChatClient(args.port, args.nick)
    await chat.setup()
    await chat.run_chat(args.connect)


if __name__ == "__main__":
    trio.run(main)