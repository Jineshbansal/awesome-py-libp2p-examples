#!/usr/bin/env python3
"""
Decentralized Chat with Peer Reputation - Basic Implementation

Initial version with basic GossipSub chat functionality.
"""

import argparse
import logging
import sys

import trio
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.stream_muxer.mplex.mplex import Mplex, MPLEX_PROTOCOL_ID
from libp2p.tools.async_service.trio_service import background_trio_service
from multiaddr import Multiaddr

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("chat")

CHAT_TOPIC = "py-libp2p-chat"
GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")


class BasicChat:
    def __init__(self, port: int, nickname: str):
        self.port = port
        self.nickname = nickname
        
       
        self.host = None
        self.pubsub = None
        
       
        self.key_pair = create_new_key_pair()
        
    async def setup_host(self):
        """Initialize libp2p host with GossipSub"""
        
    
        self.host = new_host(
            key_pair=self.key_pair,
            listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")],
            muxer_opt={MPLEX_PROTOCOL_ID: Mplex},
        )
        
        # Create basic GossipSub
        gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=3,  
            degree_low=2,  
            degree_high=4,  
        )
        self.pubsub = Pubsub(self.host, gossipsub)
        
        logger.info(f"Host started: {self.host.get_id()}")
       
        addrs = self.host.get_addrs()
        if addrs:
            for addr in addrs:
                full_addr = f"{addr}/p2p/{self.host.get_id()}"
                print(f"Listening on: {full_addr}")
        else:
            
            expected_addr = f"/ip4/127.0.0.1/tcp/{self.port}/p2p/{self.host.get_id()}"
            print(f"Listening on: {expected_addr}")
        
    async def connect_to_peer(self, peer_addr: str):
        """Connect to a peer using multiaddr string"""
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
        
    async def message_handler(self, subscription):
        """Handle incoming chat messages"""
        while True:
            try:
                message = await subscription.get()
                sender_id = message.from_id
                content = message.data.decode('utf-8')
                
              
                print(f"[{str(sender_id)[:8]}]: {content}")
                
            except Exception as e:
                logger.error(f"Error handling message: {e}")
            
    async def send_message(self, content: str):
        """Send a chat message"""
        try:
            message = f"{self.nickname}: {content}"
            await self.pubsub.publish(CHAT_TOPIC, message.encode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            
    async def run_chat(self, connect_addr: str = None):
        """Run the chat application"""
        async with self.host.run(listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")]):
            async with background_trio_service(self.pubsub):
               
                if connect_addr:
                    await self.connect_to_peer(connect_addr)
                    
              
                print(f"\n=== Basic Chat started as {self.nickname} ===")
                print("Type messages and press Enter to send")
                print("Type '/quit' to exit\n")
                
                async with trio.open_nursery() as nursery:
                    
                    nursery.start_soon(self.subscribe_to_chat)
                    
                  
                    async def input_handler():
                        while True:
                            try:
                                message = await trio.to_thread.run_sync(input)
                                if message.lower() == '/quit':
                                    break
                                await self.send_message(message)
                            except KeyboardInterrupt:
                                break
                            except Exception as e:
                                logger.error(f"Input error: {e}")
                                
                    nursery.start_soon(input_handler)


async def main():
    parser = argparse.ArgumentParser(description="Basic Decentralized Chat")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--nick", default="Anonymous", help="Your nickname")
    parser.add_argument("--connect", help="Multiaddr of peer to connect to")
    
    args = parser.parse_args()
    
   
    chat = BasicChat(args.port, args.nick)
    await chat.setup_host()
    await chat.run_chat(args.connect)


if __name__ == "__main__":
    try:
        trio.run(main)
    except KeyboardInterrupt:
        print("\nChat ended.")
        sys.exit(0)