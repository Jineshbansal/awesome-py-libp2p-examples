"""DHT-based messaging package.

This package provides serverless messaging capabilities using Kademlia DHT
for peer discovery and routing. No hardcoded bootstrap servers required -
peers can discover each other using only peer IDs.

Modules:
    kademlia: Core DHT node implementation
    chat: Simple message sending utilities
    peer: Interactive chat application
"""

from .kademlia import run_node as kademlia_run, main as kademlia_main
from .chat import send_message, send_message_once
from .peer import run as peer_run, main as peer_main

__all__ = [
    "kademlia_run",
    "kademlia_main",
    "send_message",
    "send_message_once",
    "peer_run",
    "peer_main",
]

__version__ = "1.0.0"