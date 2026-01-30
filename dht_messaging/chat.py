#!/usr/bin/env python

import argparse
import json
import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.async_service import background_trio_service

PROTOCOL_ID = TProtocol("/chat/1.0.0")


async def send_once(
    target_peer_id: str | None,
    message: str | None,
    bootstrap: str | None,
) -> None:
    from libp2p.utils.address_validation import find_free_port, get_available_interfaces

    host = new_host()
    port = find_free_port()
    listen_addrs = get_available_interfaces(port)

    async with host.run(listen_addrs=listen_addrs):
        my_id = host.get_id().pretty()
        print("\n🆔 Your Peer ID:", my_id)

        dht = KadDHT(host, DHTMode.CLIENT)

        async with background_trio_service(dht):
            # ----------------------------
            # Connect to bootstrap DHT node
            # ----------------------------
            if bootstrap:
                peer_info = info_from_p2p_addr(Multiaddr(bootstrap))
                await host.connect(peer_info)
                print("🔗 Connected to DHT bootstrap")

            # First run: no target
            if not target_peer_id:
                print("ℹ️  Run again with -t <peer-id> to send a message")
                return

            # ----------------------------
            # Resolve peer via DHT
            # ----------------------------
            value = await dht.get_value(f"/peer/{target_peer_id}")
            if not value:
                print("❌ Peer not found in DHT")
                return

            record = json.loads(value.decode())
            addr = Multiaddr(record["addrs"][0])

            peer_info = info_from_p2p_addr(
                Multiaddr(f"{addr}/p2p/{target_peer_id}")
            )

            # ----------------------------
            # Send message
            # ----------------------------
            await host.connect(peer_info)
            stream = await host.new_stream(peer_info.peer_id, [PROTOCOL_ID])
            await stream.write(message.encode())
            await stream.close()

            print(
                f"✅ Message sent to {record['username']} ({target_peer_id})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a one-shot message via DHT-discovered peer"
    )
    parser.add_argument(
        "-t",
        "--target-peer-id",
        help="PeerID to send message to",
    )
    parser.add_argument(
        "-m",
        "--message",
        help="Message text to send",
    )
    parser.add_argument(
        "-b",
        "--bootstrap",
        help="Multiaddr of a running DHT node",
    )

    args = parser.parse_args()

    try:
        trio.run(send_once, args.target_peer_id, args.message, args.bootstrap)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
