# Collaborative Notepad - Browser-to-Backend P2P Sync

A real-time collaborative text editor powered by **py-libp2p**. Multiple backend
peers sync document state over GossipSub (WebSocket transport), while browser
clients connect through a lightweight WebSocket bridge. A custom operation-based
CRDT ensures all peers converge to the same document , no central server required.

---

## Architecture

This collaborative notepad system consists of two main components: backend peers and browser clients.

- **Backend peers** run a py-libp2p host, using the WebSocket transport and GossipSub v1.1 for peer-to-peer messaging. Each backend maintains a CRDT-based document state, persisted in SQLite. Backends communicate with each other over GossipSub, propagating document operations in real time.

- **Browser clients** connect to a backend via a lightweight WebSocket bridge. The browser UI is implemented in vanilla JavaScript and communicates with the backend using a simple JSON protocol. The browser diffs local text changes and sends minimal operations to the backend, which are then broadcast to other peers.

**Tech stack:**

- Networking: py-libp2p (WebSocket transport, GossipSub pubsub)
- Sync protocol: Custom op-based CRDT (operation-based, Lamport clocks)
- Persistence: SQLite (WAL mode)
- Async runtime: Trio
- Browser: Vanilla JS + WebSocket API

**Data flow:**

1. User types in the browser. The JS client diffs the change and sends an operation to the backend over WebSocket.
2. The backend applies the operation to its CRDT, persists it, and publishes it to other backends via GossipSub.
3. Other backends receive the operation, update their CRDT and database, and forward the update to their connected browsers.
4. All browser clients see the document update in real time, with strong eventual consistency.

---

## Quick Start

### 1. Install dependencies

```bash
cd product-innovation/collaborative-notepad
pip install -r requirements.txt
```

### 2. Start the first peer

```bash
python main.py --port 8000 --ws-port 8765 --doc-id my-doc
```

You'll see output like:

```
============================================================
  Collaborative Notepad - P2P Backend
============================================================
  Document : my-doc
  Peer ID  : 16Uiu2HAm...
  libp2p   : ws://0.0.0.0:8000
  Browser  : ws://localhost:8765
  Connect  : /ip4/127.0.0.1/tcp/8000/ws/p2p/16Uiu2HAm...
```

### 3. Open the browser client

Open `static/index.html` in your browser. Set the WebSocket address to
`ws://localhost:8765` and click **Connect**.

Start typing - edits are persisted and ready to sync.

### 4. Start a second peer (optional)

Copy the `Connect` address from Peer A and run:

```bash
python main.py --port 8001 --ws-port 8766 --doc-id my-doc \
    --connect /ip4/127.0.0.1/tcp/8000/ws/p2p/16Uiu2HAm...
```

Open another browser tab pointing to `ws://localhost:8766`. Both editors
now sync in real-time through libp2p GossipSub.

---

## CLI Commands

While the backend is running, type these in the terminal:

| Command                | Description                                     |
| ---------------------- | ----------------------------------------------- |
| `/status`              | Show peer count, mesh info, document stats      |
| `/doc`                 | Print the current document text                 |
| `/peers`               | List connected libp2p peers and browser clients |
| `/connect <multiaddr>` | Connect to another backend peer                 |
| `/quit`                | Save and exit                                   |

---

## How the CRDT Works

Each character is assigned a globally unique **OpID** = `(lamport_clock, peer_id, seq)`.

- **Insert:** specifies the character and its parent (the character it goes after)
- **Delete:** tombstones a character by its OpID

Concurrent inserts at the same position are resolved deterministically by OpID
comparison (Lamport clock -> peer_id -> seq). This means all peers converge to
exactly the same text without any coordination.

Operations are **idempotent** - applying the same op twice is a no-op. This makes
the system resilient to duplicate messages, which can happen during reconnects.
