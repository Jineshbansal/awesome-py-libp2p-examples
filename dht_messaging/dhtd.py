#!/usr/bin/env python

import json
import logging
import secrets
import trio

from multiaddr import Multiaddr
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.records.validator import Validator
from libp2p.tools.async_service import background_trio_service
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream

# --------------------------------------------------
# Constants
# --------------------------------------------------

CHAT_PROTOCOL = TProtocol("/chat/1.0.0")

# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dhtd")

# --------------------------------------------------
# Validators
# --------------------------------------------------

class PeerValidator(Validator):
    def validate(self, key: str, value: bytes) -> None:
        data = json.loads(value.decode())
        if "username" not in data or "addrs" not in data:
            raise ValueError("invalid peer record")

    def select(self, key: str, values: list[bytes]) -> int:
        return 0


async def resolve_username(dht: KadDHT, peer_id: str) -> str | None:
    try:
        val = await dht.get_value(f"/peer/{peer_id}")
        if not val:
            return None
        rec = json.loads(val.decode())
        return rec.get("username")
    except Exception:
        return None

# --------------------------------------------------
# Chat handler (incoming messages)
# --------------------------------------------------

async def chat_handler(stream: INetStream):
    peer_id = stream.muxed_conn.peer_id.pretty()
    print(f"\n🟢 Incoming chat from {peer_id[:16]}...")

    try:
        while True:
            data = await stream.read(4096)
            if not data:
                print(f"\n🔴 {peer_id[:16]} disconnected")
                return
            msg = data.decode().rstrip()
            print(f"\n💬 {peer_id[:16]}: {msg}")
            print("> ", end="", flush=True)
    except Exception as e:
        log.warning(f"chat error: {e}")

# --------------------------------------------------
# Presence monitor
# --------------------------------------------------

async def presence_monitor(host):
    prev = set()
    while True:
        curr = {p.pretty() for p in host.get_connected_peers()}

        for p in curr - prev:
            print(f"\n🟢 {p[:16]} connected")

        for p in prev - curr:
            print(f"\n🔴 {p[:16]} disconnected")

        prev = curr
        await trio.sleep(1)

# --------------------------------------------------
# Interactive UI
# --------------------------------------------------

async def interactive_ui(host, dht: KadDHT):
    import sys
    stdin = trio.wrap_file(sys.stdin)

    current_stream = None
    current_peer = None

    print("\nCommands:")
    print("  list          show connected peers")
    print("  chat <num>    chat with peer")
    print("  quit          leave chat")
    print("  exit          shutdown\n")

    while True:
        print("> ", end="", flush=True)
        line = (await stdin.readline()).strip()

        if not line:
            continue

        # ---------------- active chat ----------------
        if current_stream:
            if line == "quit":
                current_stream = None
                current_peer = None
                print("⬅️  left chat\n")
            else:
                await current_stream.write((line + "\n").encode())
            continue

        parts = line.split()
        cmd = parts[0]

        # ---------------- exit ----------------
        if cmd == "exit":
            print("👋 shutting down")
            return

        # ---------------- list ----------------
        if cmd == "list":
            peers = host.get_connected_peers()
            if not peers:
                print("❌ no connected peers\n")
                continue

            print("\nConnected peers:")
            for i, p in enumerate(peers):
                pid = p.pretty()
                uname = await resolve_username(dht, pid)

                if uname:
                    print(f" [{i}] {uname} ({pid[:16]}...)")
                else:
                    print(f" [{i}] {pid[:16]}... (unknown)")
            print()
            continue

        # ---------------- chat ----------------
        if cmd == "chat":
            if len(parts) < 2:
                print("usage: chat <number>\n")
                continue

            try:
                idx = int(parts[1])
                peers = host.get_connected_peers()
                peer = peers[idx]
            except Exception:
                print("invalid peer number\n")
                continue

            try:
                stream = await host.new_stream(peer, [CHAT_PROTOCOL])
                current_stream = stream
                current_peer = peer.pretty()
                print(f"\n💬 chatting with {current_peer[:16]}")
                print("type messages, or 'quit'\n")
            except Exception as e:
                print(f"connect failed: {e}\n")

            continue

        print("unknown command\n")

# --------------------------------------------------
# DHT daemon
# --------------------------------------------------

async def run_dhtd(username: str, port: int, bootstrap: str | None, interactive: bool):
    from libp2p.utils.address_validation import get_available_interfaces

    host = new_host(key_pair=create_new_key_pair(secrets.token_bytes(32)))
    host.set_stream_handler(CHAT_PROTOCOL, chat_handler)

    async with host.run(listen_addrs=get_available_interfaces(port)), trio.open_nursery() as nursery:
        peer_id = host.get_id().pretty()

        print(f"\n🆔 {username} ({peer_id[:16]})")
        for a in host.get_addrs():
            print(" ", a)
        print()

        dht = KadDHT(host, DHTMode.SERVER)
        dht.register_validator("peer", PeerValidator())

        async with background_trio_service(dht):
            if bootstrap:
                info = info_from_p2p_addr(Multiaddr(bootstrap))
                await host.connect(info)
                log.info("bootstrapped")

            record = {
                "username": username,
                "addrs": [str(a) for a in host.get_addrs()],
            }
            await dht.put_value(f"/peer/{peer_id}", json.dumps(record).encode())
            log.info("advertised peer record")

            nursery.start_soon(presence_monitor, host)

            print(f"✅ {username} online\n")

            if interactive:
                await interactive_ui(host, dht)
            else:
                await trio.sleep_forever()

# --------------------------------------------------
# CLI
# --------------------------------------------------

def main():
    import argparse

    p = argparse.ArgumentParser("dht daemon chat")
    p.add_argument("-u", "--username", required=True)
    p.add_argument("-p", "--port", required=True, type=int)
    p.add_argument("-b", "--bootstrap")
    p.add_argument("-i", "--interactive", action="store_true")
    args = p.parse_args()

    trio.run(run_dhtd, args.username, args.port, args.bootstrap, args.interactive)

if __name__ == "__main__":
    main()
