# Collaborative Whiteboard

A peer-to-peer collaborative whiteboard application using py-libp2p with NAT traversal support. Multiple users can draw on a shared canvas in real-time without relying on central servers.

## Features

- **Real-time P2P sync** - Shapes are synchronized across all connected peers via GossipSub
- **CRDT-based state** - Last-Write-Wins semantics for conflict-free collaboration
- **Browser support** - WebSocket bridge connects browser clients to the libp2p network
- **Multiple drawing tools** - Freehand drawing, rectangles, circles, and lines
- **Peer cursors** - See where other users are drawing in real-time
- **NAT traversal ready** - Works with libp2p relay for peers behind firewalls

## Architecture

```
┌─────────────────┐         ┌─────────────────┐
│  Browser Client │◄───────►│  Browser Client │
│   (WebSocket)   │         │   (WebSocket)   │
└────────┬────────┘         └────────┬────────┘
         │                           │
         └───────────┬───────────────┘
                     │ WebSocket
              ┌──────▼──────┐
              │  Py-libp2p  │
              │ Backend Node│
              └──────┬──────┘
                     │ GossipSub
              ┌──────▼──────┐
              │ Other Peers │
              └─────────────┘
```

## Installation

```bash
cd collaborative-whiteboard
pip install -r requirements.txt
```

## Usage

### Start the first peer

```bash
python main.py --port 8001 --ws-port 8766
```

### Start additional peers (connect to the first)

```bash
python main.py --port 8002 --ws-port 8767 --peer /ip4/127.0.0.1/tcp/8001/p2p/<PEER_ID>
```

### Connect browser clients

Open `static/index.html` in your browser, or serve it:

```bash
python -m http.server 8080 --directory static
```

Then open http://localhost:8080 in your browser.

## Command Line Options

| Option          | Description                    | Default |
| --------------- | ------------------------------ | ------- |
| `--port, -p`    | libp2p listening port          | 8001    |
| `--ws-port, -w` | WebSocket bridge port          | 8766    |
| `--board, -b`   | Board ID (for multiple boards) | default |
| `--peer, -c`    | Bootstrap peer multiaddr       | None    |

## How It Works

1. **WhiteboardCRDT**: Manages the whiteboard state using Last-Write-Wins semantics
2. **WhiteboardNode**: Sets up the libp2p host with GossipSub pubsub
3. **SyncProtocol**: Handles broadcasting and receiving shape operations
4. **WebSocketBridge**: Connects browser clients to the P2P network

## Message Types

- `DRAW` - New shape added
- `DELETE_SHAPE` - Shape removed
- `CLEAR` - Board cleared
- `CURSOR` - Peer cursor position update
- `FULL_STATE` / `SYNC_REQUEST` / `SYNC_RESPONSE` - State synchronization
