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
        # Add delay for mesh formation
        await trio.sleep(2)
        
    async def message_handler(self, subscription):
        """Handle incoming chat messages with reputation validation"""
        logger.info("Message handler started for subscription")
        while True:
            try:
                message = await subscription.get()
                logger.debug(f"Raw message received: {message}")
                logger.debug(f"Message from_id type: {type(message.from_id)}")
                logger.debug(f"Message data: {message.data}")
                
               
                if hasattr(message.from_id, 'to_string'):
                    sender_id = str(message.from_id.to_string())
                else:
                    sender_id = base58.b58encode(message.from_id).decode('ascii')
                    
                content = message.data.decode('utf-8')
                logger.info(f"Processing message from {sender_id[:12]}...: {content}")
                
                if await self.reputation_system.validate_message(sender_id, content):
                    reputation = await self.reputation_system.get_peer_reputation(sender_id)
                    
                    rep_indicator = self.reputation_system.get_reputation_indicator(reputation)
                    print(f"[{sender_id[:8]}({reputation:.0f}{rep_indicator})]: {content}")
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
        
        if connected_peers:
            print("\n Connected Peers ")
            
           
            mesh_info = self.network.get_mesh_status()
            if mesh_info and mesh_info['mesh_peers']:
                print(f"GossipSub mesh peers for {CHAT_TOPIC}: {len(mesh_info['mesh_peers'])}")
                
            for peer_id in connected_peers:
                try:
                    peer_id_str = peer_id.to_string() if hasattr(peer_id, 'to_string') else str(peer_id)
                    reputation = await self.reputation_system.get_peer_reputation(peer_id_str)
                    status = self.reputation_system.get_reputation_status(reputation)
                    print(f"{peer_id_str[:15]}... - Reputation: {reputation:.1f} ({status})")
                except Exception as e:
                    logger.error(f"Error showing peer {peer_id}: {e}")
        else:
            print("No connected peers")
            
    async def show_mesh_status(self):
        """Show GossipSub mesh status for debugging"""
        try:
            mesh_info = self.network.get_mesh_status()
            if not mesh_info:
                print("No mesh information available")
                return
                
            print(f"\n GossipSub Mesh Status ")
            print(f"Topic: {mesh_info['topic']}")
            
            
            if mesh_info['mesh_peers']:
                print(f"Mesh peers ({len(mesh_info['mesh_peers'])}):")
                for peer in mesh_info['mesh_peers']:
                    peer_str = peer.to_string() if hasattr(peer, 'to_string') else str(peer)
                    print(f"  - {peer_str[:15]}...")
            else:
                print("No mesh peers (mesh might not be formed yet)")
                
           
            if mesh_info['fanout_peers']:
                print(f"Fanout peers ({len(mesh_info['fanout_peers'])}):")
                for peer in mesh_info['fanout_peers']:
                    peer_str = peer.to_string() if hasattr(peer, 'to_string') else str(peer)
                    print(f"  - {peer_str[:15]}...")
            else:
                print("No fanout peers")
                
            
            if mesh_info['all_subscribers']:
                print(f"All topic subscribers ({len(mesh_info['all_subscribers'])}):")
                for peer in mesh_info['all_subscribers']:
                    peer_str = peer.to_string() if hasattr(peer, 'to_string') else str(peer)
                    print(f"  - {peer_str[:15]}...")
            else:
                print("No subscribers")
                
        except Exception as e:
            print(f"Error accessing mesh status: {e}")
            logger.error(f"Mesh status error: {e}")
            
    async def show_reputation(self, peer_id: Optional[str]):
        """Show reputation details for a specific peer or all peers"""
        if peer_id:
            reputation = await self.reputation_system.get_peer_reputation(peer_id)
            print(f"\nReputation for {peer_id[:16]}...: {reputation:.1f}")
           
            msg_count = len(self.reputation_system.message_history.get(peer_id, []))
            print(f"Recent messages: {msg_count}\n")
        else:
            print("\n All Peer Reputations ")
            if not self.reputation_system.peer_reputations:
                print("No peer reputation data available")
            else:
                for peer, rep in self.reputation_system.peer_reputations.items():
                    status = self.reputation_system.get_reputation_status(rep)
                    print(f"{peer[:16]}... - {rep:.1f} ({status})")
            print()
            
    async def run_chat(self, connect_addr: str = None):
        """Run the chat client"""
        async with self.network.host.run(listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")]):
            async with background_trio_service(self.network.pubsub):
               
                if connect_addr:
                    await self.connect_to_peer(connect_addr)
                    
                print(f"\n  Reputation Chat started as {self.nickname} ")
                print("Type messages and press Enter to send")
                print("Commands: /quit, /peers, /reputation <peer_id>, /connect <multiaddr>, /mesh")
                print("Reputation indicators: ★=high(80+), ☆=normal(30+), ⚠=low(<30)")
                print()
                
                # Subscribe to chat topic
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
                                elif message.startswith('/mesh'):
                                    await self.show_mesh_status()
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
                                    print("Unknown command. Available: /quit, /peers, /reputation <peer_id>, /connect <multiaddr>, /mesh")
                            except KeyboardInterrupt:
                                print("Goodbye!")
                                nursery.cancel_scope.cancel()
                                break
                            except EOFError:
                                print("EOF reached, exiting...")
                                nursery.cancel_scope.cancel()
                                break
                            except Exception as e:
                                logger.error(f"Input error: {e}")
                                
                                await trio.sleep(0.1)
                                
                    nursery.start_soon(input_handler)