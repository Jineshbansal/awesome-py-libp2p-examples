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
logging.basicConfig(level=logging.INFO)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)

PROTOCOL_ID = TProtocol("/chat/1.0.0")
MAX_READ_LEN = 2**32 - 1


# ------------------------
# Stream helpers
# ------------------------

async def read_data(stream: INetStream) -> None:
    while True:
        data = await stream.read(MAX_READ_LEN)
        if data:
            msg = data.decode()
            if msg.strip():
                print(f"\x1b[32m{msg}\x1b[0m", end="")


async def write_data(stream: INetStream) -> None:
    async_f = trio.wrap_file(sys.stdin)
    while True:
        line = await async_f.readline()
        await stream.write(line.encode())


# ------------------------
# Main logic
# ------------------------

async def run(port: int, target_peer_id: str | None) -> None:
    from libp2p.utils.address_validation import find_free_port, get_available_interfaces

    if port <= 0:
        port = find_free_port()

    host = new_host()
    listen_addrs = get_available_interfaces(port)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:

        # ------------------------
        # Stream handler
        # ------------------------
        async def stream_handler(stream: INetStream) -> None:
            nursery.start_soon(read_data, stream)
            nursery.start_soon(write_data, stream)

        host.set_stream_handler(PROTOCOL_ID, stream_handler)

        # ------------------------
        # Start Kad-DHT (SERVER mode)
        # ------------------------
        dht = KadDHT(host, DHTMode.SERVER)

        async with background_trio_service(dht):
            peer_id = host.get_id()

            print("\n🆔 Peer ID:")
            print(peer_id)

            print("\n📡 Listening addresses:")
            for addr in host.get_addrs():
                print(addr)

            # ------------------------
            # Advertise self in DHT
            # ------------------------
            key = peer_id.to_bytes()
            value = b",".join(addr.to_bytes() for addr in host.get_addrs())
            await dht.put_value(f"/peer/{peer_id}", value)

            # ------------------------
            # Connect via PeerID (DHT)
            # ------------------------
            if target_peer_id:
                print(f"\n🔍 Resolving {target_peer_id} via DHT...")

                value = await dht.get_value(f"/peer/{target_peer_id}")
                if not value:
                    print("❌ Peer not found in DHT")
                else:
                    addrs = value.split(b",")
                    maddr = Multiaddr.from_bytes(addrs[0])
                    peer_info = info_from_p2p_addr(
                        Multiaddr(f"{maddr}/p2p/{target_peer_id}")
                    )

                    await host.connect(peer_info)
                    stream = await host.new_stream(peer_info.peer_id, [PROTOCOL_ID])

                    nursery.start_soon(read_data, stream)
                    nursery.start_soon(write_data, stream)

                    print("✅ Connected via DHT")

            # ------------------------
            # Periodic peer display
            # ------------------------
            async def show_peers():
                while True:
                    await trio.sleep(10)
                    peers = host.get_connected_peers()
                    print("\n🔗 Connected peers:")
                    for p in peers:
                        print(f" - {p}")
                    if not peers:
                        print(" (none)")

            nursery.start_soon(show_peers)

            await trio.sleep_forever()


# ------------------------
# CLI
# ------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="libp2p stream chat with Kad-DHT peer discovery"
    )
    parser.add_argument("-p", "--port", type=int, default=0)
    parser.add_argument(
        "-t", "--target-peer-id", help="PeerID to connect to via DHT"
    )
    args = parser.parse_args()

    try:
        trio.run(run, args.port, args.target_peer_id)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
