#!/usr/bin/env python

"""
Interactive chat application using DHT for peer discovery.
This allows peers to discover each other using only peer IDs, no hardcoded addresses.
"""

import argparse
import logging
import sys

import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.tools.async_service import background_trio_service

# Logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/chat/1.0.0")
MAX_READ_LEN = 2**32 - 1


async def read_data(stream: INetStream) -> None:
    """Read data from a stream and print it."""
    while True:
        try:
            data = await stream.read(MAX_READ_LEN)
            if data:
                msg = data.decode()
                if msg.strip():
                    print(f"\x1b[32m{msg}\x1b[0m", end="")
        except Exception:
            break


async def write_data(stream: INetStream) -> None:
    """Write data to a stream from stdin."""
    async_f = trio.wrap_file(sys.stdin)
    while True:
        try:
            line = await async_f.readline()
            await stream.write(line.encode())
        except Exception:
            break


async def run(
    port: int, 
    target_peer_id: str | None = None,
    bootstrap_addrs: list[str] | None = None
) -> None:
    """
    Run the interactive chat application.
    
    Args:
        port: Port to listen on
        target_peer_id: Optional peer ID to connect to via DHT
        bootstrap_addrs: Optional bootstrap node addresses
    """
    from libp2p.utils.address_validation import find_free_port, get_available_interfaces

    if port <= 0:
        port = find_free_port()

    listen_addrs = get_available_interfaces(port)
    host = new_host()

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        # --------------------
        # Start Kad-DHT
        # --------------------
        dht = KadDHT(host, DHTMode.SERVER)
        
        # Connect to bootstrap nodes if provided
        if bootstrap_addrs:
            for addr in bootstrap_addrs:
                try:
                    peer_info = info_from_p2p_addr(Multiaddr(addr))
                    host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 3600)
                    await host.connect(peer_info)
                    print(f"✅ Connected to bootstrap node: {addr}")
                except Exception as e:
                    print(f"❌ Failed to connect to bootstrap node {addr}: {e}")

        async with background_trio_service(dht):
            # Peerstore cleanup
            nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

            # --------------------
            # Stream handler
            # --------------------
            async def stream_handler(stream: INetStream) -> None:
                print(f"\n📨 New incoming connection from {stream.muxed_conn.peer_id}")
                nursery.start_soon(read_data, stream)
                nursery.start_soon(write_data, stream)

            host.set_stream_handler(PROTOCOL_ID, stream_handler)

            # --------------------
            # Advertise self in DHT
            # --------------------
            peer_id = host.get_id()
            peer_key = f"/peer/{peer_id.to_string()}"

            addr_bytes = b",".join(
                addr.to_bytes() for addr in host.get_addrs()
            )
            
            try:
                await dht.put_value(peer_key, addr_bytes)
                print(f"✅ Advertised peer in DHT under key: {peer_key}")
            except Exception as e:
                print(f"❌ Failed to advertise in DHT: {e}")

            print("\n🆔 Peer ID:")
            print(peer_id)

            print("\n📡 Listening addresses:")
            for addr in host.get_addrs():
                print(addr)

            # --------------------
            # Connect using PeerID (DHT)
            # --------------------
            if target_peer_id:
                print(f"\n🔍 Looking up peer {target_peer_id} in DHT...")
                target_peer_id_obj = peer_id.__class__.from_string(target_peer_id)

                peer_lookup_key = f"/peer/{target_peer_id}"
                result = await dht.get_value(peer_lookup_key)
                
                if not result:
                    print("❌ Peer not found in DHT")
                else:
                    addrs = result.split(b",")
                    maddrs = [Multiaddr.from_bytes(a) for a in addrs]

                    peer_info = info_from_p2p_addr(
                        Multiaddr(str(maddrs[0]) + f"/p2p/{target_peer_id}")
                    )

                    await host.connect(peer_info)
                    stream = await host.new_stream(peer_info.peer_id, [PROTOCOL_ID])

                    nursery.start_soon(read_data, stream)
                    nursery.start_soon(write_data, stream)

                    print("✅ Connected via DHT!")

            # --------------------
            # Show connected peers
            # --------------------
            async def print_connected_peers():
                while True:
                    await trio.sleep(30)
                    peers = host.get_network().connections
                    print("\n🔗 Connected peers:")
                    for p in peers:
                        print(f" - {p}")
                    if not peers:
                        print(" (none)")

            nursery.start_soon(print_connected_peers)

            print("\n💬 Chat is ready! Type messages and press Enter to send.")
            print("=" * 60)

            await trio.sleep_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DHT-based libp2p chat (PeerID-only discovery)"
    )
    parser.add_argument("-p", "--port", default=0, type=int)
    parser.add_argument(
        "-t",
        "--target-peer-id",
        type=str,
        help="PeerID to connect to (resolved via DHT)",
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        nargs="*",
        help="Bootstrap node addresses to connect to"
    )
    args = parser.parse_args()

    try:
        trio.run(run, args.port, args.target_peer_id, args.bootstrap)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()