# P2P + IPFS Federated Learning

A hybrid decentralized machine-learning system that combines **py-libp2p** for real-time peer-to-peer model updates with **IPFS** for persistent model checkpoint storage. Peers that go offline can rejoin later and sync to the latest model state via IPFS.

---

## Architecture

```
┌──────────────┐   libp2p pubsub    ┌──────────────┐
│   Peer A     │◄──────────────────►│   Peer B     │
│  (trainer)   │   (live updates)   │  (trainer)   │
└──────┬───────┘                    └──────┬───────┘
       │  upload checkpoint                │  fetch by CID
       ▼                                   ▼
  ┌─────────┐                         ┌─────────┐
  │  IPFS   │◄────── same CID ──────►│  IPFS   │
  │  node   │    (content-addressed)  │  node   │
  └─────────┘                         └─────────┘
       ▲
       │  fetch latest CID
┌──────┴───────┐
│   Peer C     │   (was offline, rejoins later)
│  (trainer)   │
└──────────────┘
```

### How it works

| Channel | Purpose |
|---|---|
| `fed-learn` (libp2p pubsub) | Main mesh – peers discover each other, exchange live weight updates |
| `model-cids` (libp2p pubsub) | Dedicated topic where CID announcements are broadcast (`CID:<round>:<hash>`) |
| IPFS | Long-term checkpoint storage – any peer can fetch a model by its CID |
| Local disk | Each peer keeps checkpoints under `./checkpoints_<role>/` for crash recovery |

---

## Project Structure

```
p2p-model checking/
├── p2p_ipfs_federated/
│   ├── __init__.py
│   ├── ipfs_utils.py        # Upload / download checkpoints via IPFS HTTP API
│   ├── persistence.py       # Local checkpoint save / load / prune
│   ├── coordinator.py       # Node class – libp2p + IPFS + persistence
│   ├── runner.py            # Interactive CLI entrypoint
│   └── logs.py              # Rich logging setup
├── tests/
│   └── test_integration.py  # Persistence, IPFS, and end-to-end tests
├── demo_weights.py          # Standalone demo – save, load, inspect & prune model weights
├── manual_test.py           # Full manual test suite (single-node + multi-node)
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Utility Scripts

### `demo_weights.py`

A self-contained demonstration script that walks through the **checkpoint persistence layer** step by step. It requires **no network, no IPFS credentials, and no running peers** – just Python.

**What it does (7 steps):**

| Step | Action |
|---|---|
| 1 | Generates dummy neural-network-style weights (conv, fc layers) for 5 training rounds and saves each round via `CheckpointStore` |
| 2 | Lists all saved rounds and prints the latest round number and CID |
| 3 | Reloads weights from disk for rounds 1, 3, and 5 and verifies they match the originals |
| 4 | Loads the latest checkpoint without specifying a round number |
| 5 | Inspects the raw pickle file on disk (hex dump, deserialization, parameter count) |
| 6 | Prunes old checkpoints, keeping only the last 2 rounds |
| 7 | Prints the final directory tree showing what remains on disk |

```bash
python demo_weights.py
```

Output is colour-coded with ✓/✗ match indicators. The demo writes to `./demo_checkpoints/` (cleaned automatically on each run).

---

### `manual_test.py`

A comprehensive **manual / integration test harness** that exercises the full P2P + IPFS node system with real libp2p networking. It is split into two parts:

**Part A — Single-node tests** (25 checks):

- Creates a real bootstrap `Node` and boots the libp2p + GossipSub stack.
- Runs every interactive command (`local`, `topics`, `peers`, `help`, `rounds`, `cids`, `advertize`, `publish`, `leave`, `sync`, `exit`).
- Injects dummy model weights, saves checkpoints for rounds 1–5, loads specific and latest rounds, verifies data integrity.
- Prunes checkpoints and validates the result.
- Inspects raw pickle files on disk and verifies IPFS client instantiation.

**Part B — Multi-node tests** (separate processes):

- Launches a **bootstrap node** and a **trainer node** as independent subprocesses on different ports.
- The trainer connects to the bootstrap node, joins a training topic, publishes a message, saves its own weights, and then leaves.
- Both processes' stdout is parsed for structured status lines (`CONNECTED=`, `JOINED=`, etc.) and each step is verified.
- After both processes finish, checkpoint directories for each node are inspected to confirm weights were persisted correctly.
- All temp files and checkpoint directories are cleaned up automatically.

```bash
python manual_test.py
```

At the end, a summary is printed with total pass/fail counts and a pass rate percentage.

---

## Prerequisites

| Requirement | Install |
|---|---|
| **Python 3.11+** | `brew install python@3.11` or [python.org](https://python.org) |
| **Pinata account** | Free at [pinata.cloud](https://www.pinata.cloud) – provides hosted IPFS pinning |
| **Git** | Needed to install py-libp2p from GitHub |

---

## Setup

### 1. Clone & enter the project

```bash
cd "p2p-model checking"
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
# Core + p2p
pip install -e ".[p2p,dev]"
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your Pinata credentials:

```env
PINATA_API_KEY=6e2f1f4897ed5e49361d
PINATA_API_SECRET=768c8667b685bbc653e4578f89a5e00c...
PINATA_JWT=eyJhbGciOiJIUzI1NiIs...
PINATA_GATEWAY_URL=https://gateway.pinata.cloud
```

Verify your credentials work:

```bash
curl -s https://api.pinata.cloud/data/testAuthentication \
  -H "Authorization: Bearer $PINATA_JWT" | python3 -m json.tool
```

---

## Running

### Terminal 1 – Bootstrap node

```bash
cd p2p_ipfs_federated
python runner.py
# When prompted:
#   Role: bootstrap
#   Checkpoint dir: (press Enter for default)
```

The bootstrap node will print its multiaddr, e.g.:

```
/ip4/127.0.0.1/tcp/8000/p2p/QmBootstrapPeerID...
```

### Terminal 2 – Trainer node (Peer A)

Set the bootstrap address first:

```bash
export BOOTSTRAP_ADDR="/ip4/127.0.0.1/tcp/8000/p2p/<bootstrap-peer-id>"
cd p2p_ipfs_federated
python runner.py
# Role: trainer
```

### Terminal 3 – Trainer node (Peer B)

```bash
export BOOTSTRAP_ADDR="/ip4/127.0.0.1/tcp/8000/p2p/<bootstrap-peer-id>"
cd p2p_ipfs_federated
python runner.py
# Role: trainer
```

---

## Usage – Interactive Commands

Once a node is running, use the `Command>` prompt:

### Networking

| Command | Description |
|---|---|
| `connect <multiaddr>` | Directly connect to another peer |
| `join <topic>` | Subscribe to a training mesh |
| `leave <topic>` | Leave a mesh |
| `publish <topic> <msg>` | Broadcast a message |
| `peers` | List connected peers |
| `topics` | List subscribed topics |
| `local` | Show this node's multiaddr + peer ID |

### Checkpoint & IPFS

| Command | Description |
|---|---|
| `checkpoint_save <round>` | Save in-memory weights → local disk + IPFS, broadcast CID |
| `checkpoint_load [round]` | Load weights from local disk (latest if round omitted) |
| `checkpoint_fetch <cid>` | Download a checkpoint from IPFS by CID |
| `sync` | Auto-fetch the latest known CID from IPFS (offline rejoin) |
| `cids` | Show all CIDs received from the network |
| `rounds` | List locally stored checkpoint rounds |

---

## Example Workflow

### Scenario: Peer A trains, Peer B syncs offline

```
# ── Peer A (online) ──
Command> join training-round-1

# ... Peer A trains and has weights in memory ...
# (in a real setup, training code sets node.current_weights)

Command> checkpoint_save 1
# Output: Saved checkpoint for round 1
# Output: Uploaded bytes → CID QmAbc123...
# Output: Announced CID for round 1

# ── Peer B (was offline, just started) ──
Command> sync
# Output: Syncing to round 1 via IPFS…
# Output: Fetched + saved round 1 from IPFS (CID: QmAbc123...)

Command> rounds
# Output: [1]

Command> cids
# Output: {1: "QmAbc123..."}
```

### Scenario: Crash recovery

```
# Node restarts after a crash
python runner.py
# Output: Resumed from local checkpoint round 3
# The node automatically loads its latest local checkpoint on startup
```

---

## Running Tests

```bash
# Run all tests (persistence tests always run; Pinata tests need valid credentials in .env)
pytest tests/ -v

# Run only persistence tests (no Pinata needed)
pytest tests/test_integration.py -v -k "TestCheckpointStore or TestOfflinePeer"

# Run Pinata/IPFS tests (needs valid PINATA_JWT in .env)
pytest tests/test_integration.py -v -k "TestIPFS or TestEndToEnd"
```

### Test categories

| Test class | Requires Pinata? | What it tests |
|---|---|---|
| `TestCheckpointStore` | ❌ | Local save/load/prune/delete |
| `TestIPFSClient` | ✅ | Upload/download bytes, files, JSON; pinning via Pinata |
| `TestEndToEndCheckpoint` | ✅ | Peer A uploads → Pinata/IPFS → Peer B downloads |
| `TestOfflinePeerScenario` | ❌ | Offline peer loads latest checkpoint from disk |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PINATA_API_KEY` | *(none)* | Pinata API key |
| `PINATA_API_SECRET` | *(none)* | Pinata API secret |
| `PINATA_JWT` | *(none)* | Pinata JWT token (preferred over key/secret) |
| `PINATA_GATEWAY_URL` | `https://gateway.pinata.cloud` | IPFS gateway for downloads |
| `BOOTSTRAP_ADDR` | *(none)* | Multiaddr of the bootstrap node (required for non-bootstrap peers) |
| `IP` | `127.0.0.1` | Public IP for multiaddr announcements |
| `IS_CLOUD` | `False` | Use public multiaddrs for peer connections |
| `CHECKPOINT_DIR` | `./checkpoints` | Default local checkpoint directory |

---

## Key Design Decisions

1. **Pinata IPFS API** – uses Pinata's hosted pinning service (no local IPFS daemon needed, just `requests` + API key)
2. **Pickle for weights** – simple serialisation; swap with `torch.save`/`safetensors` for production
3. **CID announcements over pubsub** – a dedicated `model-cids` topic keeps checkpoint metadata separate from training chatter
4. **Auto-resume on startup** – the runner loads the latest local checkpoint automatically so a restarted peer doesn't start from scratch
5. **Graceful IPFS fallback** – if Pinata is unreachable, the node still works with local checkpoints and live libp2p updates

---

## License

MIT
