"""Synchronization protocol for the whiteboard."""

import json
import logging
from typing import Dict, Set, Optional, Callable

import trio
from libp2p.network.stream.net_stream import NetStream
from libp2p.peer.id import ID as PeerID

from config import (
    SYNC_PROTOCOL_ID,
    TOPIC_PREFIX,
    MSG_DRAW,
    MSG_CLEAR,
    MSG_DELETE_SHAPE,
    MSG_SYNC_REQUEST,
    MSG_SYNC_RESPONSE,
    MSG_CURSOR,
    MSG_PEER_JOIN,
    MSG_PEER_LEAVE,
)
from whiteboard_crdt import WhiteboardCRDT, Shape
from node import WhiteboardNode

logger = logging.getLogger(__name__)


class SyncProtocol:
    """Handles whiteboard synchronization over libp2p."""

    def __init__(
        self,
        node: WhiteboardNode,
        whiteboard: WhiteboardCRDT,
        board_id: str
    ):
        self.node = node
        self.whiteboard = whiteboard
        self.board_id = board_id
        self.topic = f"{TOPIC_PREFIX}{board_id}"
        self.connected_peers: Set[str] = set()
        self._subscription = None
        self._running = False
        self._on_shape_added: Optional[Callable] = None
        self._on_shape_deleted: Optional[Callable] = None
        self._on_board_cleared: Optional[Callable] = None
        self._on_peer_cursor: Optional[Callable] = None

    def set_callbacks(
        self,
        on_shape_added: Optional[Callable] = None,
        on_shape_deleted: Optional[Callable] = None,
        on_board_cleared: Optional[Callable] = None,
        on_peer_cursor: Optional[Callable] = None
    ):
        """Set callbacks for whiteboard events."""
        self._on_shape_added = on_shape_added
        self._on_shape_deleted = on_shape_deleted
        self._on_board_cleared = on_board_cleared
        self._on_peer_cursor = on_peer_cursor

    async def start(self, nursery: trio.Nursery):
        """Start the sync protocol."""
        self._running = True
        self._subscription = await self.node.subscribe(self.topic)
        self.node.set_stream_handler(SYNC_PROTOCOL_ID, self._handle_sync_stream)
        nursery.start_soon(self._process_messages)
        await self._broadcast_peer_join()
        logger.info(f"Sync protocol started for board: {self.board_id}")

    async def stop(self):
        """Stop the sync protocol."""
        self._running = False
        await self._broadcast_peer_leave()
        logger.info("Sync protocol stopped")

    async def broadcast_draw(self, shape: Shape):
        """Broadcast a new shape to peers."""
        message = {
            "type": MSG_DRAW,
            "peer_id": str(self.node.get_peer_id()),
            "shape": shape.to_dict()
        }
        await self._publish(message)

    async def broadcast_delete(self, shape_id: str, timestamp: float):
        """Broadcast shape deletion to peers."""
        message = {
            "type": MSG_DELETE_SHAPE,
            "peer_id": str(self.node.get_peer_id()),
            "shape_id": shape_id,
            "timestamp": timestamp
        }
        await self._publish(message)

    async def broadcast_clear(self, timestamp: float):
        """Broadcast board clear to peers."""
        message = {
            "type": MSG_CLEAR,
            "peer_id": str(self.node.get_peer_id()),
            "timestamp": timestamp
        }
        await self._publish(message)

    async def broadcast_cursor(self, x: float, y: float):
        """Broadcast cursor position to peers."""
        message = {
            "type": MSG_CURSOR,
            "peer_id": str(self.node.get_peer_id()),
            "x": x,
            "y": y
        }
        await self._publish(message)

    async def _publish(self, message: Dict):
        """Publish a message to the topic."""
        try:
            data = json.dumps(message).encode()
            await self.node.publish(self.topic, data)
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")

    async def _process_messages(self):
        """Process incoming pubsub messages."""
        while self._running:
            try:
                msg = await self._subscription.get()
                await self._handle_message(msg.data)
            except trio.Cancelled:
                break
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                await trio.sleep(0.1)

    async def _handle_message(self, data: bytes):
        """Handle an incoming message."""
        try:
            message = json.loads(data.decode())
            msg_type = message.get("type")
            peer_id = message.get("peer_id")

            if peer_id == str(self.node.get_peer_id()):
                return

            if msg_type == MSG_DRAW:
                shape_data = message.get("shape")
                if shape_data:
                    shape = self.whiteboard.add_shape(**shape_data)
                    if shape and self._on_shape_added:
                        await self._on_shape_added(shape)

            elif msg_type == MSG_DELETE_SHAPE:
                shape_id = message.get("shape_id")
                timestamp = message.get("timestamp")
                if self.whiteboard.delete_shape(shape_id, timestamp):
                    if self._on_shape_deleted:
                        await self._on_shape_deleted(shape_id)

            elif msg_type == MSG_CLEAR:
                timestamp = message.get("timestamp")
                self.whiteboard.clear_board(timestamp)
                if self._on_board_cleared:
                    await self._on_board_cleared()

            elif msg_type == MSG_CURSOR:
                if self._on_peer_cursor:
                    await self._on_peer_cursor(
                        peer_id,
                        message.get("x", 0),
                        message.get("y", 0)
                    )

            elif msg_type == MSG_PEER_JOIN:
                self.connected_peers.add(peer_id)
                logger.info(f"Peer joined: {peer_id}")

            elif msg_type == MSG_PEER_LEAVE:
                self.connected_peers.discard(peer_id)
                logger.info(f"Peer left: {peer_id}")

        except json.JSONDecodeError:
            logger.error("Failed to decode message")

    async def _handle_sync_stream(self, stream: NetStream):
        """Handle incoming sync stream requests."""
        try:
            data = await stream.read(65536)
            request = json.loads(data.decode())

            if request.get("type") == MSG_SYNC_REQUEST:
                response = {
                    "type": MSG_SYNC_RESPONSE,
                    "state": self.whiteboard.get_state()
                }
                await stream.write(json.dumps(response).encode())

            await stream.close()
        except Exception as e:
            logger.error(f"Error handling sync stream: {e}")

    async def _broadcast_peer_join(self):
        """Broadcast peer join message."""
        message = {
            "type": MSG_PEER_JOIN,
            "peer_id": str(self.node.get_peer_id())
        }
        await self._publish(message)

    async def _broadcast_peer_leave(self):
        """Broadcast peer leave message."""
        message = {
            "type": MSG_PEER_LEAVE,
            "peer_id": str(self.node.get_peer_id())
        }
        await self._publish(message)