"""
Network layer for decentralized chat using libp2p and GossipSub.
"""

import logging

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.peer.peerstore import PeerStore
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.stream_muxer.mplex.mplex import Mplex, MPLEX_PROTOCOL_ID
from multiaddr import Multiaddr

from config import GOSSIPSUB_PROTOCOL_ID, CHAT_TOPIC

logger = logging.getLogger("network")


class ChatNetwork:
    def __init__(self, port: int):
        self.port = port
        self.host = None
        self.pubsub = None
        self.key_pair = create_new_key_pair()
        
    async def setup_host(self):
        """Initialize libp2p host with GossipSub"""
        peerstore = PeerStore()
        
        self.host = new_host(
            key_pair=self.key_pair,
            listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")],
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
            peerstore_opt=peerstore,
        )
        
        
        gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=10,
            degree_low=9,
            degree_high=11,
            time_to_live=30,
            gossip_window=3,
            gossip_history=5,
            heartbeat_initial_delay=0.1,
            heartbeat_interval=0.5,
        )
        self.pubsub = Pubsub(self.host, gossipsub)
        
        logger.info(f"Host started: {self.host.get_id()}")
        print(f"Listening on: /ip4/127.0.0.1/tcp/{self.port}/p2p/{self.host.get_id()}")
            
    async def connect_to_peer(self, peer_addr: str):
        """Connect to a peer using their multiaddr"""
        try:
            maddr = Multiaddr(peer_addr)
            info = info_from_p2p_addr(maddr)
            await self.host.connect(info)
            logger.info(f"Connected to peer: {info.peer_id}")
        except Exception as e:
            logger.error(f"Failed to connect to {peer_addr}: {e}")
            
    async def subscribe_to_chat(self):
        """Subscribe to chat topic"""
        subscription = await self.pubsub.subscribe(CHAT_TOPIC)
        logger.info(f"Subscribed to topic: {CHAT_TOPIC}")
        return subscription
        
    async def publish_message(self, message: str):
        """Publish message to chat topic"""
        await self.pubsub.publish(CHAT_TOPIC, message.encode('utf-8'))
        
    def get_connected_peers(self):
        """Get list of directly connected peers"""
        if not self.host:
            return []
        return list(self.host.get_network().connections.keys())
        
    def get_mesh_peers(self):
        """Get peers in the GossipSub mesh for our topic"""
        if not self.pubsub:
            return []
        gossipsub = self.pubsub.router
        if hasattr(gossipsub, 'mesh') and CHAT_TOPIC in gossipsub.mesh:
            return list(gossipsub.mesh[CHAT_TOPIC])
        return []
