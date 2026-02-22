"""Simple CRDT-based whiteboard state management."""

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from threading import Lock


@dataclass
class Shape:
    """Represents a shape on the whiteboard."""
    id: str
    shape_type: str
    color: str = "#000000"
    stroke_width: int = 2
    points: List[Dict[str, float]] = field(default_factory=list)
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    radius: float = 0
    timestamp: float = field(default_factory=time.time)
    peer_id: str = ""
    deleted: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Shape":
        return cls(**data)


class WhiteboardCRDT:
    """CRDT-based whiteboard using Last-Write-Wins (LWW) for shapes."""

    def __init__(self, board_id: str, peer_id: str):
        self.board_id = board_id
        self.peer_id = peer_id
        self.shapes: Dict[str, Shape] = {}
        self._lock = Lock()
        self._version = 0

    def add_shape(
        self,
        shape_type: str,
        color: str = "#000000",
        stroke_width: int = 2,
        points: Optional[List[Dict[str, float]]] = None,
        x: float = 0,
        y: float = 0,
        width: float = 0,
        height: float = 0,
        radius: float = 0,
        shape_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        peer_id: Optional[str] = None,
        deleted: bool = False
    ) -> Optional[Shape]:
        """Add a new shape to the whiteboard."""
        with self._lock:
            if len(self.shapes) >= 10000:
                return None

            if points and len(points) > 1000:
                points = points[:1000]

            shape = Shape(
                id=shape_id or str(uuid.uuid4()),
                shape_type=shape_type,
                color=color,
                stroke_width=stroke_width,
                points=points or [],
                x=x,
                y=y,
                width=width,
                height=height,
                radius=radius,
                timestamp=timestamp or time.time(),
                peer_id=peer_id or self.peer_id,
                deleted=deleted
            )

            if shape.id not in self.shapes or self.shapes[shape.id].timestamp < shape.timestamp:
                self.shapes[shape.id] = shape
                self._version += 1
                return shape
            return None

    def delete_shape(self, shape_id: str, timestamp: Optional[float] = None) -> bool:
        """Mark a shape as deleted."""
        with self._lock:
            if shape_id in self.shapes:
                ts = timestamp or time.time()
                if self.shapes[shape_id].timestamp < ts:
                    self.shapes[shape_id].deleted = True
                    self.shapes[shape_id].timestamp = ts
                    self._version += 1
                    return True
            return False

    def clear_board(self, timestamp: Optional[float] = None) -> float:
        """Clear all shapes from the board."""
        with self._lock:
            ts = timestamp or time.time()
            for shape in self.shapes.values():
                if shape.timestamp < ts:
                    shape.deleted = True
                    shape.timestamp = ts
            self._version += 1
            return ts

    def get_visible_shapes(self) -> List[Shape]:
        """Get all non-deleted shapes."""
        with self._lock:
            return [s for s in self.shapes.values() if not s.deleted]

    def get_state(self) -> Dict[str, Any]:
        """Get full state for sync."""
        with self._lock:
            return {
                "board_id": self.board_id,
                "version": self._version,
                "shapes": {sid: s.to_dict() for sid, s in self.shapes.items()}
            }

    def merge_state(self, remote_state: Dict[str, Any]) -> int:
        """Merge remote state using LWW semantics."""
        merged_count = 0
        with self._lock:
            remote_shapes = remote_state.get("shapes", {})
            for shape_id, shape_data in remote_shapes.items():
                remote_shape = Shape.from_dict(shape_data)
                if shape_id not in self.shapes:
                    self.shapes[shape_id] = remote_shape
                    merged_count += 1
                elif self.shapes[shape_id].timestamp < remote_shape.timestamp:
                    self.shapes[shape_id] = remote_shape
                    merged_count += 1
            if merged_count > 0:
                self._version += 1
        return merged_count

    @property
    def version(self) -> int:
        return self._version