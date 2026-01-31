"""
Reputation system for decentralized chat.

Handles peer reputation scoring, message validation, and spam detection.
"""

import logging
import time
from typing import Dict

from config import (
    INITIAL_REPUTATION,
    MIN_REPUTATION,
    MAX_REPUTATION,
    REPUTATION_THRESHOLD,
    MAX_MESSAGES_PER_MINUTE,
    MESSAGE_HISTORY_WINDOW,
    SPAM_PENALTY,
    NORMAL_MESSAGE_REWARD,
)

logger = logging.getLogger("reputation")


class ReputationSystem:
    def __init__(self):
        self.peer_reputations: Dict[str, float] = {}
        self.message_history: Dict[str, list] = {}
        
    async def get_peer_reputation(self, peer_id: str) -> float:
        """Get reputation score for a peer"""
        if peer_id not in self.peer_reputations:
            self.peer_reputations[peer_id] = INITIAL_REPUTATION
        return self.peer_reputations[peer_id]
        
    async def update_peer_reputation(self, peer_id: str, change: float):
        """Update peer reputation and clamp to valid range"""
        current_reputation = await self.get_peer_reputation(peer_id)
        new_reputation = max(MIN_REPUTATION, min(MAX_REPUTATION, current_reputation + change))
        
        self.peer_reputations[peer_id] = new_reputation
        logger.debug(f"Updated reputation for {peer_id[:8]}: {current_reputation:.1f} -> {new_reputation:.1f}")
            
    async def validate_message(self, peer_id: str, content: str) -> bool:
        """Validate message based on peer reputation and content"""
        reputation = await self.get_peer_reputation(peer_id)
        
        if reputation < REPUTATION_THRESHOLD:
            logger.info(f"Message from low-reputation peer {peer_id[:8]} (rep: {reputation:.1f}) filtered")
            return False
            
        # Spam detection based on message frequency
        now = time.time()
        if peer_id not in self.message_history:
            self.message_history[peer_id] = []
            
        self.message_history[peer_id] = [
            msg_time for msg_time in self.message_history[peer_id] 
            if now - msg_time < MESSAGE_HISTORY_WINDOW
        ]
        
        # Check for spam (more than MAX_MESSAGES_PER_MINUTE messages per minute)
        if len(self.message_history[peer_id]) >= MAX_MESSAGES_PER_MINUTE:
            await self.update_peer_reputation(peer_id, SPAM_PENALTY) 
            logger.info(f"Spam detected from {peer_id[:8]}, reputation decreased")
            return False
            
       
        self.message_history[peer_id].append(now)
        
       
        await self.update_peer_reputation(peer_id, NORMAL_MESSAGE_REWARD)
        
        return True
        
    def get_reputation_indicator(self, reputation: float) -> str:
        """Get visual indicator for reputation level"""
        if reputation >= 80:
            return "★"  # High reputation
        elif reputation >= REPUTATION_THRESHOLD:
            return "☆"  # Normal reputation
        else:
            return "⚠"  # Low reputation
            
    def get_reputation_status(self, reputation: float) -> str:
        """Get text status for reputation level"""
        if reputation >= 80:
            return "High"
        elif reputation >= REPUTATION_THRESHOLD:
            return "Normal"
        else:
            return "Low"