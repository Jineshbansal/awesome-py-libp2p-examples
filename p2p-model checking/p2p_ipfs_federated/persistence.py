"""
persistence.py – Local checkpoint persistence for model states.

Stores model weights + metadata (round number, CID, timestamp) on disk
so that a peer can recover state after a restart or reconnect.
"""

import json
import os
import pickle
import time
from pathlib import Path

from logs import setup_logging

logger = setup_logging("persistence")

DEFAULT_CHECKPOINT_DIR = os.getenv("CHECKPOINT_DIR", "./checkpoints")


class CheckpointStore:
    """
    Manages local model checkpoint files and their metadata.

    Directory layout:
        checkpoints/
            round_001/
                weights.pkl
                metadata.json        ← {round, cid, timestamp, peer_id, …}
            round_002/
                …
            latest.json              ← pointer to the latest round dir
    """

    def __init__(self, base_dir: str = DEFAULT_CHECKPOINT_DIR):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._latest_file = self.base_dir / "latest.json"

    # ── Save ─────────────────────────────────────────────────────────────

    def save_checkpoint(
        self,
        weights,
        round_num: int,
        peer_id: str = "",
        cid: str = "",
        extra_meta: dict | None = None,
    ) -> Path:
        """
        Persist weights and metadata for a given training round.
        Returns the directory where files were written.
        """
        round_dir = self.base_dir / f"round_{round_num:04d}"
        round_dir.mkdir(parents=True, exist_ok=True)

        # Save weights
        weights_path = round_dir / "weights.pkl"
        with open(weights_path, "wb") as f:
            pickle.dump(weights, f)

        # Build metadata
        meta = {
            "round": round_num,
            "peer_id": peer_id,
            "cid": cid,
            "timestamp": time.time(),
            "weights_file": str(weights_path),
        }
        if extra_meta:
            meta.update(extra_meta)

        meta_path = round_dir / "metadata.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        # Update the "latest" pointer
        self._write_latest(round_num)

        logger.info(f"Saved checkpoint for round {round_num} → {round_dir}")
        return round_dir

    # ── Load ─────────────────────────────────────────────────────────────

    def load_checkpoint(self, round_num: int | None = None):
        """
        Load weights and metadata for *round_num*.
        If round_num is None, loads the latest checkpoint.

        Returns (weights, metadata_dict)  or  (None, None) if not found.
        """
        if round_num is None:
            round_num = self.get_latest_round()
            if round_num is None:
                logger.warning("No checkpoint found")
                return None, None

        round_dir = self.base_dir / f"round_{round_num:04d}"
        weights_path = round_dir / "weights.pkl"
        meta_path = round_dir / "metadata.json"

        if not weights_path.exists():
            logger.warning(f"Weights file missing for round {round_num}")
            return None, None

        with open(weights_path, "rb") as f:
            weights = pickle.load(f)

        meta = {}
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)

        logger.info(f"Loaded checkpoint for round {round_num}")
        return weights, meta

    def load_weights(self, round_num: int | None = None):
        """Convenience – returns only the weights object."""
        weights, _ = self.load_checkpoint(round_num)
        return weights

    def load_metadata(self, round_num: int | None = None) -> dict | None:
        """Convenience – returns only the metadata dict."""
        _, meta = self.load_checkpoint(round_num)
        return meta

    # ── Query ────────────────────────────────────────────────────────────

    def get_latest_round(self) -> int | None:
        """Return the latest round number, or None."""
        if not self._latest_file.exists():
            return None
        with open(self._latest_file) as f:
            data = json.load(f)
        return data.get("round")

    def get_latest_cid(self) -> str | None:
        """Return the CID stored in the latest checkpoint metadata."""
        meta = self.load_metadata()
        if meta:
            return meta.get("cid")
        return None

    def list_rounds(self) -> list[int]:
        """Return sorted list of all round numbers stored locally."""
        rounds = []
        for entry in self.base_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("round_"):
                try:
                    num = int(entry.name.split("_")[1])
                    rounds.append(num)
                except ValueError:
                    pass
        return sorted(rounds)

    def has_round(self, round_num: int) -> bool:
        round_dir = self.base_dir / f"round_{round_num:04d}"
        return (round_dir / "weights.pkl").exists()

    # ── Cleanup ──────────────────────────────────────────────────────────

    def delete_round(self, round_num: int) -> bool:
        """Delete the checkpoint directory for a specific round."""
        round_dir = self.base_dir / f"round_{round_num:04d}"
        if round_dir.exists():
            import shutil
            shutil.rmtree(round_dir)
            logger.info(f"Deleted checkpoint for round {round_num}")
            return True
        return False

    def prune(self, keep_last: int = 5):
        """Keep only the *keep_last* most recent rounds, delete older ones."""
        rounds = self.list_rounds()
        if len(rounds) <= keep_last:
            return
        for r in rounds[:-keep_last]:
            self.delete_round(r)
        logger.info(f"Pruned checkpoints, kept last {keep_last}")

    # ── Internal ─────────────────────────────────────────────────────────

    def _write_latest(self, round_num: int):
        with open(self._latest_file, "w") as f:
            json.dump({"round": round_num, "updated": time.time()}, f)
