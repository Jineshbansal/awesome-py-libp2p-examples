#!/usr/bin/env python

"""
Demo script to showcase the serverless DHT messaging system.

This script demonstrates:
1. Starting a bootstrap DHT node
2. Starting peer nodes that discover each other via DHT
3. Sending messages between peers using only peer IDs
"""

import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def main():
    """Run the demo."""
    print_section("🌐 DHT-Based Serverless Messaging Demo")
    
    print("""
This demo showcases a truly serverless peer-to-peer messaging system.

Key Innovation:
✓ No hardcoded bootstrap servers needed (after initial setup)
✓ Peers discover each other using ONLY peer IDs via Kademlia DHT
✓ Direct peer-to-peer communication with no intermediaries

Architecture:
┌─────────────────────────────────────────────────────────┐
│              Kademlia DHT Network                       │
│                                                         │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐     │
│  │  Peer A  │◄────►│  Peer B  │◄────►│  Peer C  │     │
│  └──────────┘      └──────────┘      └──────────┘     │
│                                                         │
│  Each peer stores: /peer/{ID} → [multiaddrs]          │
│  Lookup happens via DHT routing (no central server)    │
└─────────────────────────────────────────────────────────┘

Setup Instructions:
""")
    
    print_section("Step 1: Start Bootstrap Node")
    print("""Run in Terminal 1:

    python -m dht_messaging.kademlia --mode server --port 5000

Expected output:
    Listener ready, listening on:
    /ip4/127.0.0.1/tcp/5000
    To connect to this node, use: --bootstrap /ip4/127.0.0.1/tcp/5000/p2p/QmXXX...

⚠️  SAVE THE BOOTSTRAP ADDRESS for next steps!
""")
    
    input("Press Enter when bootstrap node is running...")
    
    print_section("Step 2: Start Peer A (First Chat Peer)")
    print("""Run in Terminal 2:

    python -m dht_messaging.peer --port 5001 \\
      --bootstrap /ip4/127.0.0.1/tcp/5000/p2p/QmXXX...

Expected output:
    ✅ Connected to bootstrap node
    ✅ Advertised peer in DHT
    
    🆔 Peer ID:
    QmPeerA123...
    
    📡 Listening addresses:
    /ip4/127.0.0.1/tcp/5001
    
    💬 Chat is ready!

⚠️  SAVE PEER A's ID (QmPeerA123...) for the next step!
""")
    
    input("Press Enter when Peer A is running...")
    
    print_section("Step 3: Start Peer B and Connect via DHT")
    print("""Run in Terminal 3:

    python -m dht_messaging.peer --port 5002 \\
      --bootstrap /ip4/127.0.0.1/tcp/5000/p2p/QmXXX... \\
      --target-peer-id QmPeerA123...

Notice: We're using ONLY the peer ID, no direct address!

Expected output:
    ✅ Connected to bootstrap node
    ✅ Advertised peer in DHT
    🔍 Looking up peer QmPeerA123... in DHT...
    Found peer in DHT!
    Connecting to peer...
    ✅ Connected via DHT!
    
    💬 Chat is ready!

🎉 SUCCESS! Peer B found Peer A using ONLY its ID via the DHT!
""")
    
    input("Press Enter to continue...")
    
    print_section("Step 4: Chat Between Peers")
    print("""
Now you can type messages in either terminal:

Terminal 2 (Peer A):
    > Hello from Peer A!

Terminal 3 (Peer B):
    [Receives] Hello from Peer A!
    > Hi Peer A, this is Peer B!

Terminal 2 (Peer A):
    [Receives] Hi Peer A, this is Peer B!

Messages flow DIRECTLY between peers, no server involved!
""")
    
    input("Press Enter to see one-shot messaging example...")
    
    print_section("Bonus: One-Shot Messaging")
    print("""
You can also send single messages programmatically:

    python -m dht_messaging.chat \\
      --target-peer-id QmPeerA123... \\
      --message "Quick message!" \\
      --bootstrap /ip4/127.0.0.1/tcp/5000/p2p/QmXXX...

This will:
1. Query DHT for peer address
2. Connect to peer
3. Send message
4. Exit

Perfect for automation and scripting!
""")
    
    input("Press Enter to see advanced features...")
    
    print_section("🚀 Advanced Features")
    print("""
1. Custom Validators
   - Add domain-specific validation for DHT keys
   - Example: Signature verification, schema validation

2. Programmatic Integration
   from dht_messaging import send_message, peer_run
   
   # Send a message
   send_message("QmPeer123...", "Hello!", bootstrap_addrs=[...])
   
   # Start a peer programmatically
   import trio
   trio.run(peer_run, 5001, "QmTarget...", [...])

3. Network Modes
   - Server Mode: Maintains DHT, stores peer data
   - Client Mode: Queries only, for mobile/ephemeral peers

4. Production Deployment
   - Run on public IPs for global network
   - Use multiple bootstrap nodes for redundancy
   - Implement NAT traversal for firewalled peers
""")
    
    input("Press Enter to see next steps...")
    
    print_section("📚 What You've Learned")
    print("""
✓ Distributed Hash Tables (Kademlia implementation)
✓ libp2p peer-to-peer networking primitives  
✓ Serverless architecture patterns
✓ Asynchronous programming with Trio
✓ Network protocol design (multiaddr, streams)

Real-World Applications:
• Decentralized chat applications
• P2P file sharing networks
• Blockchain node discovery
• IoT device communication
• Censorship-resistant messaging
""")
    
    print_section("🎯 Key Takeaways")
    print("""
1. DHT eliminates need for centralized discovery servers
2. Peers can find each other using cryptographic IDs only
3. System is truly serverless after initial bootstrap
4. Scalable to thousands of peers without infrastructure
5. Foundation for building production dApps

Ready to build your own serverless applications? 🚀

Check out the README.md for full documentation!
""")
    
    print("\n" + "=" * 70)
    print("  Demo Complete! Happy Hacking! 🎉")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nDemo interrupted. Goodbye! 👋\n")