"""WebSocket bridge for browser clients."""

import json
import logging
import time
from typing import Dict, Set, Optional

import trio
from trio_websocket import (
    serve_websocket,
    WebSocketConnection,
    WebSocketRequest,
    ConnectionClosed,
)

from whiteboard_crdt import WhiteboardCRDT, Shape
from sync_protocol import SyncProtocol
from config import DEFAULT_WS_BRIDGE_PORT

logger = logging.getLogger(__name__)


class WebSocketBridge:
    """Bridge between browser WebSocket clients and libp2p network."""

    def __init__(
        self,
        whiteboard: WhiteboardCRDT,
        sync_protocol: SyncProtocol,
        port: int = DEFAULT_WS_BRIDGE_PORT
    ):
        self.whiteboard = whiteboard
        self.sync_protocol = sync_protocol
        self.port = port
        self.clients: Set[WebSocketConnection] = set()

    async def start(self, nursery: trio.Nursery):
        """Start the WebSocket server."""
        self.sync_protocol.set_callbacks(
            on_shape_added=self._on_remote_shape_added,
            on_shape_deleted=self._on_remote_shape_deleted,
            on_board_cleared=self._on_remote_board_cleared,
            on_peer_cursor=self._on_remote_peer_cursor
        )

        nursery.start_soon(
            serve_websocket,
            self._handle_request,
            "0.0.0.0",
            self.port,
            None,  # ssl_context
        )

        logger.info(f"WebSocket bridge started on port {self.port}")

    async def _handle_request(self, request: WebSocketRequest):
        """Handle a new WebSocket connection request."""
        ws = await request.accept()
        self.clients.add(ws)
        client_id = id(ws)
        logger.info(f"Client connected: {client_id}")

        try:
            await self._send_full_state(ws)

            while True:
                try:
                    message = await ws.get_message()
                    await self._process_client_message(ws, message)
                except ConnectionClosed:
                    break

        except Exception as e:
            logger.error(f"Client error: {e}")
        finally:
            self.clients.discard(ws)
            logger.info(f"Client disconnected: {client_id}")

    async def _process_client_message(
        self,
        websocket: WebSocketConnection,
        message: str
    ):
        """Process a message from a browser client."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "draw":
                shape = self.whiteboard.add_shape(
                    shape_type=data.get("shape_type", "stroke"),
                    color=data.get("color", "#000000"),
                    stroke_width=data.get("stroke_width", 2),
                    points=data.get("points"),
                    x=data.get("x", 0),
                    y=data.get("y", 0),
                    width=data.get("width", 0),
                    height=data.get("height", 0),
                    radius=data.get("radius", 0)
                )
                if shape:
                    await self.sync_protocol.broadcast_draw(shape)
                    await self._broadcast_to_clients({
                        "type": "shape_added",
                        "shape": shape.to_dict()
                    }, exclude=websocket)

            elif msg_type == "delete":
                shape_id = data.get("shape_id")
                timestamp = time.time()
                if self.whiteboard.delete_shape(shape_id, timestamp):
                    await self.sync_protocol.broadcast_delete(shape_id, timestamp)
                    await self._broadcast_to_clients({
                        "type": "shape_deleted",
                        "shape_id": shape_id
                    }, exclude=websocket)

            elif msg_type == "clear":
                timestamp = self.whiteboard.clear_board()
                await self.sync_protocol.broadcast_clear(timestamp)
                await self._broadcast_to_clients({
                    "type": "board_cleared"
                }, exclude=websocket)

            elif msg_type == "cursor":
                await self.sync_protocol.broadcast_cursor(
                    data.get("x", 0),
                    data.get("y", 0)
                )

        except json.JSONDecodeError:
            logger.error("Invalid JSON from client")

    async def _send_full_state(self, websocket: WebSocketConnection):
        """Send full whiteboard state to a client."""
        shapes = self.whiteboard.get_visible_shapes()
        message = {
            "type": "full_state",
            "shapes": [s.to_dict() for s in shapes]
        }
        await websocket.send_message(json.dumps(message))

    async def _broadcast_to_clients(
        self,
        message: Dict,
        exclude: Optional[WebSocketConnection] = None
    ):
        """Broadcast a message to all connected clients."""
        data = json.dumps(message)
        for client in list(self.clients):
            if client != exclude:
                try:
                    await client.send_message(data)
                except ConnectionClosed:
                    self.clients.discard(client)

    async def _on_remote_shape_added(self, shape: Shape):
        """Handle shape added from remote peer."""
        await self._broadcast_to_clients({
            "type": "shape_added",
            "shape": shape.to_dict()
        })

    async def _on_remote_shape_deleted(self, shape_id: str):
        """Handle shape deleted from remote peer."""
        await self._broadcast_to_clients({
            "type": "shape_deleted",
            "shape_id": shape_id
        })

    async def _on_remote_board_cleared(self):
        """Handle board cleared from remote peer."""
        await self._broadcast_to_clients({
            "type": "board_cleared"
        })

    async def _on_remote_peer_cursor(self, peer_id: str, x: float, y: float):
        """Handle cursor update from remote peer."""
        await self._broadcast_to_clients({
            "type": "peer_cursor",
            "peer_id": peer_id,
            "x": x,
            "y": y
        })