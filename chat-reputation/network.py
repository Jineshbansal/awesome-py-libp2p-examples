"""
Network layer for decentralized chat using libp2p and GossipSub.
"""

import logging
from typing import Optional

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
        # Create basic peerstore (in-memory)
        peerstore = PeerStore()
        
        # Create host with peerstore
        self.host = new_host(
            key_pair=self.key_pair,
            listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")],
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
            peerstore_opt=peerstore,
        )
        
        # Create GossipSub with required parameters
        gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=3,  
            degree_low=2,  
            degree_high=4,  
        )
        self.pubsub = Pubsub(self.host, gossipsub)
        
        logger.info(f"Host started: {self.host.get_id()}")
        
        # Print all listening multiaddrs for easy peer connection
        addrs = self.host.get_addrs()
        if addrs:
            for addr in addrs:
                full_addr = f"{addr}/p2p/{self.host.get_id()}"
                print(f"Listening on: {full_addr}")
        else:
            expected_addr = f"/ip4/127.0.0.1/tcp/{self.port}/p2p/{self.host.get_id()}"
            print(f"Listening on: {expected_addr}")
            
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
        """Subscribe to chat topic and return subscription"""
        subscription = await self.pubsub.subscribe(CHAT_TOPIC)
        logger.info(f"Subscribed to topic: {CHAT_TOPIC}")
        return subscription
        
    async def publish_message(self, message: str):
        """Publish message to chat topic"""
        await self.pubsub.publish(CHAT_TOPIC, message.encode('utf-8'))
        
    def get_connected_peers(self):
        """Get list of connected peers"""
        if not self.host:
            return []
        return list(self.host.get_network().connections.keys())
        
    def get_mesh_status(self):
        """Get GossipSub mesh status for debugging"""
        if not self.pubsub:
            return None
            
        gossipsub = self.pubsub.router
        
        mesh_info = {
            'topic': CHAT_TOPIC,
            'mesh_peers': [],
            'fanout_peers': [],
            'all_subscribers': []
        }
        
        try:
            if hasattr(gossipsub, 'mesh') and CHAT_TOPIC in gossipsub.mesh:
                mesh_info['mesh_peers'] = list(gossipsub.mesh[CHAT_TOPIC])
                
            if hasattr(gossipsub, 'fanout') and CHAT_TOPIC in gossipsub.fanout:
                mesh_info['fanout_peers'] = list(gossipsub.fanout[CHAT_TOPIC])
                
            if hasattr(gossipsub, 'peer_topics'):
                mesh_info['all_subscribers'] = list(gossipsub.peer_topics.get(CHAT_TOPIC, set()))
                
        except Exception as e:
            logger.error(f"Error accessing mesh status: {e}")
            
        return mesh_info