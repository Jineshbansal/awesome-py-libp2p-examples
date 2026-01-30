import json
import logging
import secrets
import trio
from typing import Optional, Dict

from multiaddr import Multiaddr
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.records.validator import Validator
from libp2p.tools.async_service import background_trio_service
from libp2p.peer.peerinfo import info_from_p2p_addr



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dht-node")



class PeerValidator(Validator):
    def validate(self, key: str, value: bytes) -> None:
        data = json.loads(value.decode())
        if "username" not in data or "addrs" not in data:
            raise ValueError("Invalid peer record")
        if not data["addrs"]:
            raise ValueError("Empty address list")

    def select(self, key: str, values: list[bytes]) -> int:
        return 0




async def resolve_peer(dht: KadDHT, peer_id: str) -> Optional[Dict]:
    try:
        value = await dht.get_value(f"/peer/{peer_id}")
        if not value:
            return None
        return json.loads(value.decode())
    except Exception as e:
        logger.debug(f"Could not resolve peer {peer_id}: {e}")
        return None




async def start_dht_node(
    username: str,
    port: int = 0,
    connect_peer_id: Optional[str] = None,
    bootstrap_addr: Optional[str] = None,
) -> None:
    from libp2p.utils.address_validation import find_free_port, get_available_interfaces

    if port <= 0:
        port = find_free_port()

    keypair = create_new_key_pair(secrets.token_bytes(32))
    host = new_host(key_pair=keypair)
    listen_addrs = get_available_interfaces(port)

    async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        my_peer_id = host.get_id().pretty()

        print("\n🆔 Peer ID:", my_peer_id)
        print("👤 Username:", username)
        print("📡 Addresses:")
        for a in host.get_addrs():
            print(" ", a)

        dht = KadDHT(host, DHTMode.SERVER)
        dht.register_validator("peer", PeerValidator())

        async with background_trio_service(dht):
            # Advertise self
            record = {
                "username": username,
                "addrs": [str(a) for a in host.get_addrs()],
            }

            await dht.put_value(
                f"/peer/{my_peer_id}",
                json.dumps(record).encode(),
            )

            logger.info("Peer advertised in DHT")

            # Bootstrap (optional)
            if bootstrap_addr:
                print(f"\n🔗 Connecting to bootstrap node...")
                info = info_from_p2p_addr(Multiaddr(bootstrap_addr))
                await host.connect(info)
                logger.info("Connected to bootstrap node")
                
                # Try to resolve bootstrap peer's username
                bootstrap_peer_id = info.peer_id.pretty()
                peer_info = await resolve_peer(dht, bootstrap_peer_id)
                if peer_info:
                    print(f"✅ Bootstrap peer: {peer_info['username']} ({bootstrap_peer_id})")
                else:
                    print(f"✅ Connected to: {bootstrap_peer_id}")

            # Connect to peer via DHT (optional)
            if connect_peer_id:
                print(f"\n🔍 Resolving peer {connect_peer_id} via DHT...")
                peer = await resolve_peer(dht, connect_peer_id)
                if not peer:
                    print("❌ Peer not found")
                else:
                    print("✅ Peer found:", peer["username"])
                    addr = Multiaddr(peer["addrs"][0])
                    peer_info = info_from_p2p_addr(
                        Multiaddr(f"{addr}/p2p/{connect_peer_id}")
                    )
                    await host.connect(peer_info)
                    print(f"🔗 Connected to {peer['username']} ({connect_peer_id})")

            # Status loop - FIXED INDENTATION
            async def status():
                while True:
                    await trio.sleep(10)
                    print("\n🔗 Connected peers:")

                    peers = host.get_connected_peers()
                    if not peers:
                        print("  (none)")
                        continue

                    for p in peers:
                        peer_id = p.pretty()
                        info = await resolve_peer(dht, peer_id)

                        if info:
                            print(f"  - {info['username']} ({peer_id})")
                        else:
                            print(f"  - {peer_id} (unknown)")

            nursery.start_soon(status)

            # Keep running
            await trio.sleep_forever()