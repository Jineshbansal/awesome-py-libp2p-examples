"""
Configuration constants for decentralized chat with reputation system.
"""

from libp2p.custom_types import TProtocol

# Chat configuration
CHAT_TOPIC = "py-libp2p-chat"
GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.0.0")

# Reputation system constants
INITIAL_REPUTATION = 50
MIN_REPUTATION = 0
MAX_REPUTATION = 100
REPUTATION_THRESHOLD = 30  # Minimum reputation to have messages displayed
REPUTATION_DECAY_RATE = 0.1  # Daily reputation decay

# Spam detection
MAX_MESSAGES_PER_MINUTE = 5
MESSAGE_HISTORY_WINDOW = 60  # seconds
SPAM_PENALTY = -5.0
NORMAL_MESSAGE_REWARD = 0.1

# Network configuration
DEFAULT_PORT = 8000
DEFAULT_DATA_DIR = "./chat_data"