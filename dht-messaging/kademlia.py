#!/usr/bin/env python

"""
A Kademlia DHT implementation for serverless peer discovery.
This module demonstrates both value storage/retrieval and peer advertisement/discovery.
"""

import argparse
import logging
import os
import random
import secrets
import sys

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.records.validator import Validator
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.utils import info_from_p2p_addr
from libp2p.utils.paths import get_script_dir, join_paths


# Custom validator for the "peer" namespace
class PeerValidator(Validator):
    """
    A simple validator for the 'peer' namespace.
    This validator is used to store peer addresses in the DHT.
    """

    def validate(self, key: str, value: bytes) -> None:
        """Validate a key-value pair."""
        if not value:
            raise ValueError("Value cannot be empty")

    def select(self, key: str, values: list[bytes]) -> int:
        """Select the best value from a list of values."""
        # Always return the first value (most recent)
        return 0


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("kademlia-dht")

# Get the directory where this script is located
SCRIPT_DIR = get_script_dir(__file__)
SERVER_ADDR_LOG = join_paths(SCRIPT_DIR, "server_node_addr.txt")

# File to store node information
bootstrap_nodes = []


async def connect_to_bootstrap_nodes(host: IHost, bootstrap_addrs: list[str]) -> None:
    """
    Connect to the bootstrap nodes provided in the list.

    Args:
        host: The host instance to connect to
        bootstrap_addrs: List of bootstrap node addresses
    """
    for addr in bootstrap_addrs:
        try:
            peerInfo = info_from_p2p_addr(Multiaddr(addr))
            host.get_peerstore().add_addrs(peerInfo.peer_id, peerInfo.addrs, 3600)
            await host.connect(peerInfo)
            logger.info(f"Connected to bootstrap node: {addr}")
        except Exception as e:
            logger.error(f"Failed to connect to bootstrap node {addr}: {e}")


def save_server_addr(addr: str) -> None:
    """Append the server's multiaddress to the log file."""
    try:
        with open(SERVER_ADDR_LOG, "w") as f:
            f.write(addr + "\n")
        logger.info(f"Saved server address to log: {addr}")
    except Exception as e:
        logger.error(f"Failed to save server address: {e}")


def load_server_addrs() -> list[str]:
    """Load all server multiaddresses from the log file."""
    if not os.path.exists(SERVER_ADDR_LOG):
        return []
    try:
        with open(SERVER_ADDR_LOG) as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        logger.error(f"Failed to load server addresses: {e}")
        return []


async def run_node(
    port: int, mode: str, bootstrap_addrs: list[str] | None = None
) -> None:
    """Run a DHT node for serverless peer discovery."""
    try:
        if port <= 0:
            port = random.randint(10000, 60000)
        logger.debug(f"Using port: {port}")

        # Convert string mode to DHTMode enum
        if mode is None or mode.upper() == "CLIENT":
            dht_mode = DHTMode.CLIENT
        elif mode.upper() == "SERVER":
            dht_mode = DHTMode.SERVER
        else:
            logger.error(f"Invalid mode: {mode}. Must be 'client' or 'server'")
            sys.exit(1)

        # Load server addresses for client mode
        if dht_mode == DHTMode.CLIENT:
            server_addrs = load_server_addrs()
            if server_addrs:
                logger.info(f"Loaded {len(server_addrs)} server addresses from log")
                bootstrap_nodes.append(server_addrs[0])
            else:
                logger.warning("No server addresses found in log file")

        if bootstrap_addrs:
            for addr in bootstrap_addrs:
                bootstrap_nodes.append(addr)

        key_pair = create_new_key_pair(secrets.token_bytes(32))
        host = new_host(key_pair=key_pair)

        from libp2p.utils.address_validation import (
            get_available_interfaces,
            get_optimal_binding_address,
        )

        listen_addrs = get_available_interfaces(port)

        async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
            # Start the peer-store cleanup task
            nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

            peer_id = host.get_id().pretty()

            # Get all available addresses with peer ID
            all_addrs = host.get_addrs()

            logger.info("Listener ready, listening on:")
            for addr in all_addrs:
                logger.info(f"{addr}")

            # Use optimal address for the bootstrap command
            optimal_addr = get_optimal_binding_address(port)
            optimal_addr_with_peer = f"{optimal_addr}/p2p/{host.get_id().to_string()}"
            bootstrap_cmd = f"--bootstrap {optimal_addr_with_peer}"
            logger.info("To connect to this node, use: %s", bootstrap_cmd)

            await connect_to_bootstrap_nodes(host, bootstrap_nodes)
            dht = KadDHT(host, dht_mode)

            # Register a custom validator for the "peer" namespace
            dht.register_validator("peer", PeerValidator())
            logger.info("Registered custom 'peer' namespace validator")

            # Add connected peers to the routing table
            for peer_id in host.get_peerstore().peer_ids():
                await dht.routing_table.add_peer(peer_id)
            logger.info(f"Connected to bootstrap nodes: {host.get_connected_peers()}")

            # Save server address in server mode
            if dht_mode == DHTMode.SERVER:
                save_server_addr(str(optimal_addr_with_peer))

            # Start the DHT service
            async with background_trio_service(dht):
                logger.info(f"DHT service started in {dht_mode.value} mode")

                # Advertise this peer's addresses in the DHT
                peer_id_obj = host.get_id()
                peer_key = f"/peer/{peer_id_obj.to_string()}"
                
                # Store all addresses as comma-separated bytes
                addr_bytes = b",".join(addr.to_bytes() for addr in host.get_addrs())
                
                try:
                    await dht.put_value(peer_key, addr_bytes)
                    logger.info(f"Advertised peer addresses in DHT under key: {peer_key}")
                except Exception as e:
                    logger.error(f"Failed to advertise peer in DHT: {e}")

                # Keep the node running
                while True:
                    logger.info(
                        "Status - Connected peers: %d, "
                        "Peers in store: %d, Values in store: %d",
                        len(dht.host.get_connected_peers()),
                        len(dht.host.get_peerstore().peer_ids()),
                        len(dht.value_store.store),
                    )
                    await trio.sleep(10)

    except Exception as e:
        logger.error(f"Node error: {e}", exc_info=True)
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kademlia DHT node for serverless peer discovery"
    )
    parser.add_argument(
        "--mode",
        default="server",
        help="Run as a server or client node",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (0 for random)",
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        nargs="*",
        help=(
            "Multiaddrs of bootstrap nodes. "
            "Provide a space-separated list of addresses."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()
    
    # Set logging level based on verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    return args


def main():
    """Main entry point for the kademlia DHT node."""
    try:
        args = parse_args()
        logger.info(
            "Running in %s mode on port %d",
            args.mode,
            args.port,
        )
        trio.run(run_node, args.port, args.mode, args.bootstrap)
    except Exception as e:
        logger.critical(f"Script failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()