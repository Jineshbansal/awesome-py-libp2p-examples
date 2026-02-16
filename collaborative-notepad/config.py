"""Configuration for the Collaborative Notepad P2P application."""

from libp2p.custom_types import TProtocol

# --- Network ---
DEFAULT_LIBP2P_PORT = 8000
DEFAULT_WS_BRIDGE_PORT = 8765
DATA_DIR = "./notepad_data"

# --- Protocols ---
GOSSIPSUB_PROTOCOL_ID = TProtocol("/meshsub/1.1.0")
SYNC_PROTOCOL_ID = TProtocol("/notepad/sync/1.0.0")

# --- PubSub ---
TOPIC_PREFIX = "/collab/notepad/"
DEFAULT_DOC_ID = "default"

# --- CRDT ---
MAX_DOC_SIZE = 500_000  # characters
OP_BATCH_INTERVAL = 0.05  # seconds — debounce for batching ops

# --- Message types sent over PubSub / WS bridge ---
MSG_INSERT = "INSERT"
MSG_DELETE = "DELETE"
MSG_FULL_STATE = "FULL_STATE"
MSG_SYNC_REQUEST = "SYNC_REQUEST"
MSG_SYNC_RESPONSE = "SYNC_RESPONSE"
MSG_CURSOR = "CURSOR"
MSG_PEER_JOIN = "PEER_JOIN"
MSG_PEER_LEAVE = "PEER_LEAVE"

# --- GossipSub tuning ---
GOSSIPSUB_DEGREE = 6
GOSSIPSUB_DEGREE_LOW = 4
GOSSIPSUB_DEGREE_HIGH = 8
GOSSIPSUB_HEARTBEAT_INTERVAL = 1
GOSSIPSUB_HEARTBEAT_INITIAL_DELAY = 0.5
GOSSIPSUB_TIME_TO_LIVE = 60
GOSSIPSUB_GOSSIP_WINDOW = 3
GOSSIPSUB_GOSSIP_HISTORY = 5
