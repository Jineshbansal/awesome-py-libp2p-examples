"""Reputation storage and peer identity management."""

import json
import logging
import time
from pathlib import Path

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.id import ID

from config import (
    INITIAL_REPUTATION, MIN_REPUTATION, MAX_REPUTATION, MAX_MESSAGES_PER_MINUTE
)

logger = logging.getLogger("chat")


def load_or_create_key(data_dir: str, port: int):
    """Load existing key pair or create new one. Ensures same peer ID across restarts."""
    key_file = Path(data_dir) / f"peer_key_{port}.json"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    
    if key_file.exists():
        try:
            with open(key_file) as f:
                data = json.load(f)
            secret = bytes.fromhex(data["private_key"])
            return create_new_key_pair(secret)
        except Exception as e:
            logger.warning(f"Could not load key: {e}, creating new one")
    
    key_pair = create_new_key_pair()
    with open(key_file, "w") as f:
        json.dump({"private_key": key_pair.private_key.to_bytes().hex()}, f)
    return key_pair


class ReputationStore:
    """Persists peer reputation scores to disk and syncs with gossipsub."""
    
    def __init__(self, data_dir: str, gossipsub=None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.data_dir / "reputations.json"
        self.scores: dict[str, float] = self._load()
        self.message_times: dict[str, list[float]] = {}
        self.gossipsub = gossipsub
    
    def _load(self) -> dict[str, float]:
        if self.file_path.exists():
            try:
                with open(self.file_path) as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def save(self):
        with open(self.file_path, "w") as f:
            json.dump(self.scores, f)
    
    def get_reputation(self, peer_id: str) -> float:
        return self.scores.get(peer_id, INITIAL_REPUTATION)
    
    def update_reputation(self, peer_id: str, delta: float):
        current = self.get_reputation(peer_id)
        new_rep = max(MIN_REPUTATION, min(MAX_REPUTATION, current + delta))
        self.scores[peer_id] = new_rep
        self.save()
        self._sync_to_gossipsub(peer_id, new_rep)
    
    def _sync_to_gossipsub(self, peer_id_str: str, reputation: float):
        """Sync reputation to gossipsub scorer."""
        if not self.gossipsub or not self.gossipsub.scorer:
            return
        try:
            peer_id = ID.from_base58(peer_id_str)
            penalty = max(0, (INITIAL_REPUTATION - reputation) / 10)
            if penalty > 0:
                self.gossipsub.scorer.penalize_behavior(peer_id, penalty)
        except:
            pass
    
    def apply_saved_penalties(self):
        """Apply penalties for known bad peers on startup."""
        if not self.gossipsub or not self.gossipsub.scorer:
            return
        for peer_id_str, rep in self.scores.items():
            if rep < INITIAL_REPUTATION:
                self._sync_to_gossipsub(peer_id_str, rep)
    
    def is_spam(self, peer_id: str) -> bool:
        now = time.time()
        times = self.message_times.get(peer_id, [])
        times = [t for t in times if now - t < 60]
        self.message_times[peer_id] = times
        
        if len(times) >= MAX_MESSAGES_PER_MINUTE:
            return True
        
        self.message_times[peer_id].append(now)
        return False
