# Decentralized Chat with Peer Reputation

A spam-resistant chat application using libp2p's GossipSub protocol with peer scoring.

## Features

- **GossipSub messaging**: Decentralized pub/sub for message distribution
- **Peer Scoring**: Uses libp2p's gossipsub v1.1 peer scoring to penalize bad actors
- **Reputation Persistence**: Stores peer reputations to disk across sessions
- **Spam Detection**: Rate-limits messages (>10/min) and down-scores spammers
- **Persistent Identity**: Each peer maintains same ID across restarts (per-port keys)

## How It Works

1. Peers connect via libp2p and join a gossipsub mesh
2. Each message sender is tracked with a reputation score (0-100)
3. Spammers (>10 msgs/minute) get penalized (-15 reputation)
4. Good peers slowly gain reputation (+1 per message)
5. Messages from peers with reputation < 20 are blocked
6. Reputation syncs with gossipsub scoring (bad reputation = behavior penalty)
7. Reputations and peer keys persist to disk

## Quick Start

```bash
cd chat-reputation
pip install -r requirements.txt
```

**Terminal 1 - Start first peer:**

```bash
python main.py -p 9000 -n Alice
```

**Terminal 2 - Connect second peer:**

```bash
python main.py -p 9001 -n Bob -c /ip4/127.0.0.1/tcp/9000/p2p/<PEER_ID_FROM_TERMINAL_1>
```

## Commands

| Command   | Description                                       |
| --------- | ------------------------------------------------- |
| `/status` | Show connected peers and live session reputations |
| `/stored` | Show all persisted reputations from disk          |
| `/spam`   | Demo: simulate spam to show down-scoring          |
| `/quit`   | Exit the chat                                     |

## Demo: Bad Actor Down-Scoring

1. Start two peers and connect them
2. Send a few normal messages (watch reputation increase)
3. Type `/spam` to simulate a bad actor
4. Check `/status` to see the spammer's reputation drop
5. Restart the app - reputation persists! Check with `/stored`

## Scoring Details

**Reputation System (0-100):**

- Initial score: 50
- Good message: +1
- Spam detected: -15
- Block threshold: < 20

**GossipSub Peer Scoring:**

- Publish threshold: -50 (can't publish below this)
- Gossip threshold: -100 (excluded from gossip)
- Graylist threshold: -200 (fully ignored)
