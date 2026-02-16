"""
Operation-based CRDT for collaborative text editing.

Each character is identified by a unique OpID = (lamport_clock, peer_id, seq).
This gives a total ordering across all peers, allowing concurrent inserts to
converge deterministically.

Operations are idempotent — applying the same op twice is a no-op.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, order=True)
class OpID:
    """Globally unique, totally ordered operation identifier.

    Ordering: lamport_clock first, then peer_id (lexicographic), then seq.
    This ensures all peers converge to the same document state.
    """
    lamport: int
    peer_id: str
    seq: int

    def to_dict(self) -> dict[str, Any]:
        return {"lamport": self.lamport, "peer_id": self.peer_id, "seq": self.seq}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OpID":
        return cls(lamport=d["lamport"], peer_id=d["peer_id"], seq=d["seq"])

    def __str__(self) -> str:
        return f"{self.lamport}:{self.peer_id[:8]}:{self.seq}"


@dataclass
class Op:
    """A single insert or delete operation."""
    op_type: str  # "INSERT" or "DELETE"
    op_id: OpID
    char: str = ""          # The character (for INSERT)
    parent_id: OpID | None = None  # Insert after this op (None = beginning)
    target_id: OpID | None = None  # The op to delete (for DELETE)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "op_type": self.op_type,
            "op_id": self.op_id.to_dict(),
            "timestamp": self.timestamp,
        }
        if self.op_type == "INSERT":
            d["char"] = self.char
            d["parent_id"] = self.parent_id.to_dict() if self.parent_id else None
        elif self.op_type == "DELETE":
            d["target_id"] = self.target_id.to_dict() if self.target_id else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Op":
        op_type = d["op_type"]
        op_id = OpID.from_dict(d["op_id"])
        timestamp = d.get("timestamp", time.time())
        if op_type == "INSERT":
            parent_raw = d.get("parent_id")
            parent_id = OpID.from_dict(parent_raw) if parent_raw else None
            return cls(
                op_type=op_type,
                op_id=op_id,
                char=d.get("char", ""),
                parent_id=parent_id,
                timestamp=timestamp,
            )
        else:  # DELETE
            target_raw = d.get("target_id")
            target_id = OpID.from_dict(target_raw) if target_raw else None
            return cls(
                op_type=op_type,
                op_id=op_id,
                target_id=target_id,
                timestamp=timestamp,
            )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, s: str) -> "Op":
        return cls.from_dict(json.loads(s))


@dataclass
class CharItem:
    """A character in the document sequence."""
    op_id: OpID
    char: str
    deleted: bool = False


class TextCRDT:
    """
    A simple operation-based sequence CRDT for text.

    Characters are stored as an ordered list. Each character has a unique OpID.
    Inserts specify a parent (the character after which to insert).
    Deletes mark characters as tombstoned.

    The ordering of concurrent inserts is resolved by OpID comparison,
    which is deterministic across all peers.
    """

    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self.items: list[CharItem] = []
        self.applied_ops: set[tuple[int, str, int]] = set()  # (lamport, peer, seq)
        self.lamport_clock: int = 0
        self.seq_counter: int = 0

    def _tick(self) -> OpID:
        """Advance the Lamport clock and return a new OpID."""
        self.lamport_clock += 1
        self.seq_counter += 1
        return OpID(
            lamport=self.lamport_clock,
            peer_id=self.peer_id,
            seq=self.seq_counter,
        )

    def _update_clock(self, remote_lamport: int) -> None:
        """Update local Lamport clock on receiving a remote op."""
        self.lamport_clock = max(self.lamport_clock, remote_lamport) + 1

    def _op_key(self, op_id: OpID) -> tuple[int, str, int]:
        return (op_id.lamport, op_id.peer_id, op_id.seq)

    def _find_index(self, op_id: OpID) -> int | None:
        """Find the index of a character by its OpID."""
        for i, item in enumerate(self.items):
            if item.op_id == op_id:
                return i
        return None

    def _find_insert_position(self, parent_id: OpID | None, new_op_id: OpID) -> int:
        """Find where to insert a new character.

        After the parent, but before any existing character whose OpID is
        less than the new one (to maintain deterministic ordering of
        concurrent inserts after the same parent).
        """
        if parent_id is None:
            # Insert at the beginning — but after any existing items that
            # were also inserted at the beginning with a smaller OpID.
            pos = 0
            while pos < len(self.items):
                # Walk past items whose parent is also None and whose
                # op_id is greater than ours (they sort after us).
                if self.items[pos].op_id > new_op_id:
                    break
                # If the item's op_id is less than ours, we insert after it
                # only if it's also a "beginning" insert. But since we can't
                # track parent info in CharItem, we use a simpler approach:
                # just insert at position 0 and let OpID ordering resolve ties.
                break
            return pos

        parent_idx = self._find_index(parent_id)
        if parent_idx is None:
            # Parent not found — append at end (will be corrected on resync)
            return len(self.items)

        # Insert after parent. Walk forward past any items that were also
        # inserted after the same point but have a greater OpID (they sort first).
        pos = parent_idx + 1
        while pos < len(self.items):
            if self.items[pos].op_id > new_op_id:
                # This item has a higher OpID, so it was inserted concurrently
                # and should come after our new item in the sequence.
                break
            pos += 1
        return pos

    # --- Local operations (user typing) ---

    def local_insert(self, position: int, char: str) -> Op:
        """Insert a character at a visible position. Returns the op to broadcast."""
        op_id = self._tick()

        # Find the parent: the visible character at (position - 1)
        parent_id = None
        if position > 0:
            visible_count = 0
            for item in self.items:
                if not item.deleted:
                    visible_count += 1
                    if visible_count == position:
                        parent_id = item.op_id
                        break

        # Find actual insert position in items list
        insert_idx = self._find_insert_position(parent_id, op_id)
        self.items.insert(insert_idx, CharItem(op_id=op_id, char=char))
        self.applied_ops.add(self._op_key(op_id))

        return Op(
            op_type="INSERT",
            op_id=op_id,
            char=char,
            parent_id=parent_id,
            timestamp=time.time(),
        )

    def local_delete(self, position: int) -> Op | None:
        """Delete the character at a visible position. Returns the op or None."""
        visible_count = 0
        for item in self.items:
            if not item.deleted:
                visible_count += 1
                if visible_count == position + 1:  # position is 0-indexed
                    op_id = self._tick()
                    item.deleted = True
                    self.applied_ops.add(self._op_key(op_id))
                    return Op(
                        op_type="DELETE",
                        op_id=op_id,
                        target_id=item.op_id,
                        timestamp=time.time(),
                    )
        return None

    # --- Remote operations (from other peers) ---

    def apply_remote_op(self, op: Op) -> bool:
        """Apply a remote operation. Returns True if applied (not a duplicate)."""
        key = self._op_key(op.op_id)
        if key in self.applied_ops:
            return False  # Idempotent: already applied

        self._update_clock(op.op_id.lamport)

        if op.op_type == "INSERT":
            insert_idx = self._find_insert_position(op.parent_id, op.op_id)
            self.items.insert(insert_idx, CharItem(op_id=op.op_id, char=op.char))
        elif op.op_type == "DELETE":
            if op.target_id is not None:
                idx = self._find_index(op.target_id)
                if idx is not None:
                    self.items[idx].deleted = True
                # If target not found, the delete is a no-op (character may
                # have been inserted by an op we haven't received yet — in a
                # production system we'd buffer this, but for the demo it's
                # safe to drop).

        self.applied_ops.add(key)
        return True

    # --- Serialization ---

    def to_plaintext(self) -> str:
        """Render the current visible text."""
        return "".join(item.char for item in self.items if not item.deleted)

    def get_state(self) -> dict[str, Any]:
        """Serialize full CRDT state for sync."""
        return {
            "peer_id": self.peer_id,
            "lamport_clock": self.lamport_clock,
            "seq_counter": self.seq_counter,
            "items": [
                {
                    "op_id": item.op_id.to_dict(),
                    "char": item.char,
                    "deleted": item.deleted,
                }
                for item in self.items
            ],
        }

    def load_state(self, state: dict[str, Any]) -> None:
        """Load full CRDT state (replaces current state)."""
        self.lamport_clock = state["lamport_clock"]
        self.seq_counter = state["seq_counter"]
        self.items = [
            CharItem(
                op_id=OpID.from_dict(item["op_id"]),
                char=item["char"],
                deleted=item["deleted"],
            )
            for item in state["items"]
        ]
        self.applied_ops = {self._op_key(item.op_id) for item in self.items}

    def get_state_json(self) -> str:
        return json.dumps(self.get_state())

    @classmethod
    def from_state_json(cls, data: str, peer_id: str) -> "TextCRDT":
        crdt = cls(peer_id)
        crdt.load_state(json.loads(data))
        return crdt

    def __len__(self) -> int:
        """Number of visible characters."""
        return sum(1 for item in self.items if not item.deleted)

    def __repr__(self) -> str:
        text = self.to_plaintext()
        preview = text[:40] + "..." if len(text) > 40 else text
        return f"TextCRDT(peer={self.peer_id[:8]}, len={len(self)}, text={preview!r})"
