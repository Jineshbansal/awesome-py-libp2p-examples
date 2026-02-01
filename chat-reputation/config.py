"""Configuration for decentralized chat with peer reputation."""

from libp2p.custom_types import TProtocol

CHAT_TOPIC = "py-libp2p-reputation-chat"
GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.1.0")

INITIAL_REPUTATION = 50.0
MIN_REPUTATION = 0.0
MAX_REPUTATION = 100.0
REPUTATION_THRESHOLD = 20.0

MAX_MESSAGES_PER_MINUTE = 10
SPAM_PENALTY = -15.0
GOOD_MESSAGE_REWARD = 1.0

DEFAULT_PORT = 8000
DATA_DIR = "./reputation_data"