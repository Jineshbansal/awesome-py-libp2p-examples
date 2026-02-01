"""Chat application with reputation-based message filtering."""

import logging

import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.score import ScoreParams, TopicScoreParams
from libp2p.tools.async_service.trio_service import background_trio_service

from config import (
    CHAT_TOPIC, GOSSIPSUB_PROTOCOL_ID, REPUTATION_THRESHOLD,
    SPAM_PENALTY, GOOD_MESSAGE_REWARD, MAX_MESSAGES_PER_MINUTE
)
from reputation_system import ReputationStore, load_or_create_key

logger = logging.getLogger("chat")


class ChatApp:
    """Main chat application combining gossipsub, peer scoring, and reputation persistence."""
    
    def __init__(self, port: int, nickname: str, data_dir: str):
        self.port = port
        self.nickname = nickname
        self.data_dir = data_dir
        self.reputation_store = None
        self.host = None
        self.pubsub = None
        self.gossipsub = None
    
    def _create_score_params(self) -> ScoreParams:
        """Create peer scoring parameters for spam resistance."""
        return ScoreParams(
            p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=100.0, decay=0.99),
            p2_first_message_deliveries=TopicScoreParams(weight=2.0, cap=50.0, decay=0.95),
            p4_invalid_messages=TopicScoreParams(weight=10.0, cap=100.0, decay=0.9),
            p5_behavior_penalty_weight=5.0,
            p5_behavior_penalty_decay=0.9,
            p5_behavior_penalty_threshold=1.0,
            publish_threshold=-50.0,
            gossip_threshold=-100.0,
            graylist_threshold=-200.0,
        )
    
    async def setup(self):
        key_pair = load_or_create_key(self.data_dir, self.port)
        self.host = new_host(key_pair=key_pair)
        
        self.gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=6,
            degree_low=4,
            degree_high=8,
            time_to_live=60,
            gossip_window=3,
            gossip_history=5,
            heartbeat_initial_delay=0.5,
            heartbeat_interval=1,
            score_params=self._create_score_params(),
        )
        self.pubsub = Pubsub(self.host, self.gossipsub)
        
        self.reputation_store = ReputationStore(self.data_dir, self.gossipsub)
        self.reputation_store.apply_saved_penalties()
        if self.reputation_store.scores:
            print(f"Loaded {len(self.reputation_store.scores)} saved reputations")
    
    def _get_peer_str(self, peer_id) -> str:
        if hasattr(peer_id, 'to_string'):
            return peer_id.to_string()
        return str(peer_id)
    
    def _format_reputation(self, rep: float) -> str:
        if rep >= 80:
            return f"{rep:.0f}★"
        elif rep >= REPUTATION_THRESHOLD:
            return f"{rep:.0f}☆"
        else:
            return f"{rep:.0f}⚠"
    
    async def handle_message(self, subscription):
        """Process incoming messages with reputation-based filtering."""
        while True:
            try:
                msg = await subscription.get()
                sender_bytes = msg.from_id
                sender_id = self._get_peer_str(ID(sender_bytes) if isinstance(sender_bytes, bytes) else sender_bytes)
                content = msg.data.decode('utf-8')
                
                rep = self.reputation_store.get_reputation(sender_id)
                
                if rep < REPUTATION_THRESHOLD:
                    logger.info(f"Blocked message from low-rep peer {sender_id[:8]}... (rep={rep:.0f})")
                    continue
                
                if self.reputation_store.is_spam(sender_id):
                    self.reputation_store.update_reputation(sender_id, SPAM_PENALTY)
                    self.gossipsub.scorer.penalize_behavior(ID(sender_bytes) if isinstance(sender_bytes, bytes) else sender_bytes, 5.0)
                    print(f"[SPAM DETECTED] {sender_id[:8]}... penalized!")
                    continue
                
                self.reputation_store.update_reputation(sender_id, GOOD_MESSAGE_REWARD)
                rep = self.reputation_store.get_reputation(sender_id)
                print(f"[{sender_id[:8]}|{self._format_reputation(rep)}] {content}")
                
            except Exception as e:
                logger.error(f"Message error: {e}")
    
    async def send_message(self, content: str):
        message = f"{self.nickname}: {content}"
        await self.pubsub.publish(CHAT_TOPIC, message.encode('utf-8'))
    
    async def show_status(self):
        """Display network and connected peer status."""
        peers = list(self.host.get_network().connections.keys())
        mesh = list(self.gossipsub.mesh.get(CHAT_TOPIC, set()))
        
        print(f"\n[STATUS] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"Your ID: {self._get_peer_str(self.host.get_id())[:16]}...")
        print(f"Connected: {len(peers)} peers | Mesh: {len(mesh)} peers")
        
        if peers:
            print("\nConnected Peers:")
            for peer_id in peers:
                peer_str = self._get_peer_str(peer_id)
                rep = self.reputation_store.get_reputation(peer_str)
                
                gossip_score = 0.0
                if self.gossipsub.scorer:
                    gossip_score = self.gossipsub.scorer.score(peer_id, [CHAT_TOPIC])
                
                status = "✓" if rep >= REPUTATION_THRESHOLD else "✗"
                print(f"  {status} {peer_str[:16]}... rep={rep:.0f} gscore={gossip_score:.1f}")
        else:
            print("No connected peers yet")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    def show_stored(self):
        """Display all stored reputations from disk."""
        print(f"\n[STORED] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if not self.reputation_store.scores:
            print("No stored reputations yet")
        else:
            print(f"Total: {len(self.reputation_store.scores)} peers")
            for pid, score in self.reputation_store.scores.items():
                indicator = self._format_reputation(score)
                status = "✓" if score >= REPUTATION_THRESHOLD else "✗ BLOCKED"
                print(f"  {status} {pid[:20]}... = {indicator}")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    async def simulate_bad_actor(self):
        """Simulate spam to demonstrate down-scoring."""
        print(f"\n[SPAM TEST] Sending {MAX_MESSAGES_PER_MINUTE + 3} rapid messages...")
        for i in range(MAX_MESSAGES_PER_MINUTE + 3):
            await self.send_message(f"spam #{i+1}")
            await trio.sleep(0.1)
        print("[SPAM TEST] Done! Other peers will see you as a spammer.\n")
    
    async def run(self, connect_addr: str = None):
        listen_addr = Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")
        
        async with self.host.run(listen_addrs=[listen_addr]):
            async with background_trio_service(self.pubsub):
                print(f"\n{'='*50}")
                print(f"Reputation Chat - {self.nickname}")
                print(f"{'='*50}")
                print(f"Your address: /ip4/127.0.0.1/tcp/{self.port}/p2p/{self.host.get_id()}")
                print(f"\nCommands: /status /stored /spam /quit")
                print(f"Messages from peers with rep < {REPUTATION_THRESHOLD} are blocked")
                print(f"{'='*50}\n")
                
                if connect_addr:
                    try:
                        info = info_from_p2p_addr(Multiaddr(connect_addr))
                        await self.host.connect(info)
                        print(f"Connected to: {info.peer_id}")
                        await trio.sleep(1)
                    except Exception as e:
                        print(f"Connection failed: {e}")
                
                subscription = await self.pubsub.subscribe(CHAT_TOPIC)
                
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(self.handle_message, subscription)
                    
                    while True:
                        try:
                            user_input = await trio.to_thread.run_sync(input)
                            
                            if user_input.lower() == '/quit':
                                print("Goodbye!")
                                nursery.cancel_scope.cancel()
                                break
                            elif user_input.lower() == '/status':
                                await self.show_status()
                            elif user_input.lower() == '/stored':
                                self.show_stored()
                            elif user_input.lower() == '/spam':
                                await self.simulate_bad_actor()
                            elif user_input.strip() and not user_input.startswith('/'):
                                await self.send_message(user_input)
                                
                        except (KeyboardInterrupt, EOFError):
                            nursery.cancel_scope.cancel()
                            break
