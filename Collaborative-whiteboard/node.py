"""Libp2p node setup for the collaborative whiteboard."""

import logging
from typing import Optional, Callable, Awaitable

import trio
from libp2p import new_host
from libp2p.host.basic_host import BasicHost
from libp2p.network.stream.net_stream import NetStream
from libp2p.peer.id import ID as PeerID
from libp2p.peer.peerinfo import PeerInfo, info_from_p2p_addr
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.custom_types import TProtocol
from libp2p.tools.async_service.trio_service import background_trio_service
from multiaddr import Multiaddr

from config import (
    DEFAULT_LIBP2P_PORT,
    GOSSIPSUB_PROTOCOL_ID,
    GOSSIPSUB_DEGREE,
    GOSSIPSUB_DEGREE_LOW,
    GOSSIPSUB_DEGREE_HIGH,
    GOSSIPSUB_HEARTBEAT_INTERVAL,
)

logger = logging.getLogger(__name__)


class WhiteboardNode:
    """Libp2p node for whiteboard synchronization."""

    def __init__(self, port: int = DEFAULT_LIBP2P_PORT):
        self.port = port
        self.host: Optional[BasicHost] = None
        self.pubsub: Optional[Pubsub] = None
        self.gossipsub: Optional[GossipSub] = None
        self._started = False

    def setup(self) -> PeerID:
        """Create the host and pubsub objects (non-async setup)."""
        if self._started:
            return self.host.get_id()

        self.host = new_host()

        self.gossipsub = GossipSub(
            protocols=[GOSSIPSUB_PROTOCOL_ID],
            degree=GOSSIPSUB_DEGREE,
            degree_low=GOSSIPSUB_DEGREE_LOW,
            degree_high=GOSSIPSUB_DEGREE_HIGH,
            time_to_live=60,
            heartbeat_interval=GOSSIPSUB_HEARTBEAT_INTERVAL,
        )
        self.pubsub = Pubsub(self.host, self.gossipsub)

        self._started = True
        peer_id = self.host.get_id()
        logger.info(f"Node created with peer ID: {peer_id}")
        return peer_id

    def get_listen_addrs(self):
        """Get the multiaddr list to listen on."""
        return [Multiaddr(f"/ip4/0.0.0.0/tcp/{self.port}")]

    def get_peer_id(self) -> Optional[PeerID]:
        """Get the node's peer ID."""
        return self.host.get_id() if self.host else None

    def get_addrs(self) -> list:
        """Get listening addresses."""
        if not self.host:
            return []
        return [
            f"{addr}/p2p/{self.host.get_id()}"
            for addr in self.host.get_addrs()
        ]

    async def connect_to_peer(self, multiaddr_str: str) -> bool:
        """Connect to a peer using multiaddr."""
        try:
            maddr = Multiaddr(multiaddr_str)
            peer_info = info_from_p2p_addr(maddr)
            await self.host.connect(peer_info)
            logger.info(f"Connected to peer: {peer_info.peer_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to peer: {e}")
            return False

    async def subscribe(self, topic: str):
        """Subscribe to a pubsub topic. Returns a subscription object."""
        if not self.pubsub:
            raise RuntimeError("Node not set up")
        return await self.pubsub.subscribe(topic)

    async def publish(self, topic: str, data: bytes):
        """Publish data to a pubsub topic."""
        if not self.pubsub:
            raise RuntimeError("Node not set up")
        await self.pubsub.publish(topic, data)

    def set_stream_handler(
        self,
        protocol: TProtocol,
        handler: Callable[[NetStream], Awaitable[None]]
    ):
        """Set a handler for incoming streams."""
        if self.host:
            self.host.set_stream_handler(protocol, handler)

    async def new_stream(
        self,
        peer_id: PeerID,
        protocols: list
    ) -> NetStream:
        """Open a new stream to a peer."""
        return await self.host.new_stream(peer_id, protocols)