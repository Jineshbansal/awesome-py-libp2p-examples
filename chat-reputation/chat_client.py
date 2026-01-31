"""
Chat client with reputation-based message handling.
"""

import logging
from typing import Optional

import base58
import trio
from libp2p.tools.async_service.trio_service import background_trio_service
from multiaddr import Multiaddr

from config import CHAT_TOPIC
from network import ChatNetwork
from reputation_system import ReputationSystem

logger = logging.getLogger("chat")


class ChatClient:
    def __init__(self, port: int, nickname: str):
        self.port = port
        self.nickname = nickname
        self.network = ChatNetwork(port)
        self.reputation_system = ReputationSystem()
        
    async def setup(self):
        """Initialize the chat client"""
        await self.network.setup_host()
        
    async def connect_to_peer(self, peer_addr: str):
        """Connect to a peer"""
        await self.network.connect_to_peer(peer_addr)
        await trio.sleep(2)  # Wait for mesh formation
        
    async def message_handler(self, subscription):
        """Handle incoming chat messages with reputation validation"""
        logger.info("Message handler started for subscription")
        while True:
            try:
                message = await subscription.get()
                
                # Get sender ID
                if hasattr(message.from_id, 'to_string'):
                    sender_id = str(message.from_id.to_string())
                else:
                    sender_id = base58.b58encode(message.from_id).decode('ascii')
                    
                content = message.data.decode('utf-8')
                logger.info(f"Processing message from {sender_id[:12]}...: {content}")
                
                # Validate message based on reputation
                if await self.reputation_system.validate_message(sender_id, content):
                    reputation = await self.reputation_system.get_peer_reputation(sender_id)
                    rep_indicator = self.reputation_system.get_reputation_indicator(reputation)
                    print(f"[{sender_id[:8]}]  | Rep: {reputation:.0f} [{rep_indicator}] | {content}")
                    logger.info(f"Message displayed from {sender_id[:12]}...")
                else:
                    logger.warning(f"Message from {sender_id[:12]}... failed validation")
                    
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                
    async def send_message(self, content: str):
        """Send a chat message"""
        try:
            message = f"{self.nickname}: {content}"
            logger.info(f"Publishing message: {message}")
            await self.network.publish_message(message)
            logger.info(f"Message published successfully")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            
    async def show_peers(self):
        """Show connected peers and their reputations"""
        connected_peers = self.network.get_connected_peers()
        mesh_peers = self.network.get_mesh_peers()
        
        print(f"\nNetwork Status:")
        print(f"Direct connections: {len(connected_peers)}")
        print(f"Mesh peers (for message relay): {len(mesh_peers)}")
        
        if connected_peers:
            print("\nConnected peers:")
            for peer_id in connected_peers:
                try:
                    peer_str = peer_id.to_string() if hasattr(peer_id, 'to_string') else str(peer_id)
                    reputation = await self.reputation_system.get_peer_reputation(peer_str)
                    status = self.reputation_system.get_reputation_status(reputation)
                    print(f"  {peer_str[:16]}... - Rep: {reputation:.1f} ({status})")
                except Exception as e:
                    logger.error(f"Error showing peer {peer_id}: {e}")
        else:
            print("\nNo connected peers")
            
    async def show_reputation(self, peer_id: Optional[str]):
        """Show reputation details"""
        if peer_id:
            reputation = await self.reputation_system.get_peer_reputation(peer_id)
            print(f"\nReputation for {peer_id[:16]}...: {reputation:.1f}")
        else:
            print("\nAll Peer Reputations:")
            if not self.reputation_system.peer_reputations:
                print("No reputation data yet")
            else:
                for peer, rep in self.reputation_system.peer_reputations.items():
                    status = self.reputation_system.get_reputation_status(rep)
                    print(f"  {peer[:16]}... - {rep:.1f} ({status})")
            
    async def run_chat(self, connect_addr: str = None):
        """Run the chat client"""
        async with self.network.host.run(listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")]):
            async with background_trio_service(self.network.pubsub):
                if connect_addr:
                    await self.connect_to_peer(connect_addr)
                    
                print(f"\nReputation Chat started as {self.nickname}")
                print("Commands: /peers, /reputation, /quit")
                print("Reputation: high=80+, normal=30+, low=<30")
                print()
                
                subscription = await self.network.subscribe_to_chat()
                
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(self.message_handler, subscription)
                    
                    async def input_handler():
                        while True:
                            try:
                                message = await trio.to_thread.run_sync(input)
                                if message.lower() == '/quit':
                                    print("Goodbye!")
                                    nursery.cancel_scope.cancel()
                                    break
                                elif message.startswith('/peers'):
                                    await self.show_peers()
                                elif message.startswith('/reputation'):
                                    parts = message.split(' ', 1)
                                    peer_id = parts[1] if len(parts) > 1 and parts[1].strip() else None
                                    await self.show_reputation(peer_id)
                                elif message.startswith('/connect '):
                                    peer_addr = message.split(' ', 1)[1] if len(message.split(' ', 1)) > 1 else None
                                    if peer_addr:
                                        await self.connect_to_peer(peer_addr)
                                elif message.strip() and not message.startswith('/'):
                                    await self.send_message(message)
                                elif message.startswith('/'):
                                    print("Commands: /peers, /reputation, /connect <addr>, /quit")
                            except KeyboardInterrupt:
                                print("Goodbye!")
                                nursery.cancel_scope.cancel()
                                break
                            except EOFError:
                                nursery.cancel_scope.cancel()
                                break
                            except Exception as e:
                                logger.error(f"Input error: {e}")
                                await trio.sleep(0.1)
                                
                    nursery.start_soon(input_handler)
