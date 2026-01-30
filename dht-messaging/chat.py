#!/usr/bin/env python

"""
Chat module for DHT-based messaging.
This allows sending messages to peers discovered via the DHT.
"""

import argparse
import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.async_service import background_trio_service

# Protocol used by the example chat streams
PROTOCOL_ID = TProtocol("/chat/1.0.0")


async def send_message_once(
    target_peer_id: str, 
    message: str, 
    port: int = 0,
    bootstrap_addrs: list[str] | None = None
) -> None:
    """
    Resolve `target_peer_id` using the DHT and send a single message.

    This starts a minimal host, runs a DHT client to resolve the peer's
    advertised addresses (under the key `/peer/{peer_id}`) and opens a
    libp2p stream to write the provided message, then exits.
    
    Args:
        target_peer_id: The peer ID to send the message to
        message: The message to send
        port: Local port to bind (0 for auto)
        bootstrap_addrs: Bootstrap node addresses to connect to
    """
    from libp2p.utils.address_validation import find_free_port, get_available_interfaces

    if port <= 0:
        port = find_free_port()

    host = new_host()
    listen_addrs = get_available_interfaces(port)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # Run DHT in client mode so we can resolve peer entries
        dht = KadDHT(host, DHTMode.CLIENT)
        
        # Connect to bootstrap nodes if provided
        if bootstrap_addrs:
            for addr in bootstrap_addrs:
                try:
                    peer_info = info_from_p2p_addr(Multiaddr(addr))
                    host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 3600)
                    await host.connect(peer_info)
                    print(f"Connected to bootstrap node: {addr}")
                except Exception as e:
                    print(f"Failed to connect to bootstrap node {addr}: {e}")

        async with background_trio_service(dht):
            # Look up peer info in DHT; the examples store peer addrs under /peer/{id}
            peer_key = f"/peer/{target_peer_id}"
            print(f"Looking up peer {target_peer_id} in DHT...")
            
            value = await dht.get_value(peer_key)
            if not value:
                raise RuntimeError(f"Peer {target_peer_id} not found in DHT")

            print(f"Found peer in DHT!")
            
            # Parse the stored addresses
            addrs = value.split(b",")
            maddr = Multiaddr.from_bytes(addrs[0])
            peer_info = info_from_p2p_addr(Multiaddr(f"{maddr}/p2p/{target_peer_id}"))

            # Connect and open a stream to send the message
            print(f"Connecting to peer...")
            await host.connect(peer_info)
            stream = await host.new_stream(peer_info.peer_id, [PROTOCOL_ID])

            # Write the message and close the stream
            print(f"Sending message: {message}")
            await stream.write(message.encode())
            
            # Small pause to allow write to flush
            await trio.sleep(0.1)
            await stream.close()
            print("Message sent successfully!")


def send_message(
    target_peer_id: str, 
    message: str, 
    port: int = 0,
    bootstrap_addrs: list[str] | None = None
) -> None:
    """Synchronous wrapper around the async send helper."""
    trio.run(send_message_once, target_peer_id, message, port, bootstrap_addrs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send one message to a peer resolved via the DHT"
    )
    parser.add_argument(
        "-t", "--target-peer-id", 
        required=True, 
        help="Target PeerID to send to"
    )
    parser.add_argument(
        "-m", "--message", 
        required=True, 
        help="Message text to send"
    )
    parser.add_argument(
        "-p", "--port", 
        type=int, 
        default=0, 
        help="Local port to bind (0 for auto)"
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        nargs="*",
        help="Bootstrap node addresses to connect to"
    )
    args = parser.parse_args()

    try:
        send_message(args.target_peer_id, args.message, args.port, args.bootstrap)
    except Exception as e:
        print(f"Error sending message: {e}")


if __name__ == "__main__":
    main()