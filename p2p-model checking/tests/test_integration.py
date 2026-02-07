"""
Tests for the P2P + IPFS Federated Learning system.

Run:  pytest tests/ -v

Tests are split into:
  1. Unit tests for persistence (no network needed)
  2. Unit tests for IPFS/Pinata (needs valid Pinata API credentials)
  3. Integration tests for multi-peer scenarios
"""

import json
import os
import pickle
import shutil
import sys
import tempfile
import time

import pytest
from dotenv import load_dotenv

# Load .env so Pinata creds are available
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Ensure the package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "p2p_ipfs_federated"))

from persistence import CheckpointStore
from ipfs_utils import IPFSClient


# ═══════════════════════════════════════════════════════════════════════════
#  1.  Persistence tests  (no external deps)
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckpointStore:
    """Test local checkpoint save / load / prune."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ckpt_test_")
        self.store = CheckpointStore(base_dir=self.tmpdir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_load(self):
        weights = {"layer1": [1.0, 2.0], "layer2": [3.0]}
        self.store.save_checkpoint(weights, round_num=1, peer_id="peer-A")

        loaded_w, meta = self.store.load_checkpoint(1)
        assert loaded_w == weights
        assert meta["round"] == 1
        assert meta["peer_id"] == "peer-A"

    def test_load_latest(self):
        self.store.save_checkpoint({"v": 1}, round_num=1)
        self.store.save_checkpoint({"v": 2}, round_num=2)
        self.store.save_checkpoint({"v": 3}, round_num=5)

        w, meta = self.store.load_checkpoint()  # should load round 5
        assert w == {"v": 3}
        assert meta["round"] == 5

    def test_list_rounds(self):
        for r in [3, 1, 7, 2]:
            self.store.save_checkpoint({"r": r}, round_num=r)
        assert self.store.list_rounds() == [1, 2, 3, 7]

    def test_has_round(self):
        self.store.save_checkpoint({"x": 1}, round_num=4)
        assert self.store.has_round(4) is True
        assert self.store.has_round(99) is False

    def test_delete_round(self):
        self.store.save_checkpoint({"x": 1}, round_num=10)
        assert self.store.has_round(10)
        self.store.delete_round(10)
        assert not self.store.has_round(10)

    def test_prune_keeps_last_n(self):
        for r in range(1, 11):
            self.store.save_checkpoint({"r": r}, round_num=r)
        self.store.prune(keep_last=3)
        assert self.store.list_rounds() == [8, 9, 10]

    def test_load_nonexistent_returns_none(self):
        w, m = self.store.load_checkpoint(999)
        assert w is None
        assert m is None

    def test_cid_stored_in_metadata(self):
        self.store.save_checkpoint({"w": 1}, round_num=1, cid="QmFakeCid123")
        _, meta = self.store.load_checkpoint(1)
        assert meta["cid"] == "QmFakeCid123"

    def test_get_latest_cid(self):
        self.store.save_checkpoint({"w": 1}, round_num=1, cid="Qm111")
        self.store.save_checkpoint({"w": 2}, round_num=2, cid="Qm222")
        assert self.store.get_latest_cid() == "Qm222"


# ═══════════════════════════════════════════════════════════════════════════
#  2.  IPFS/Pinata tests  (need valid Pinata API credentials)
# ═══════════════════════════════════════════════════════════════════════════

def ipfs_available() -> bool:
    """Return True if Pinata API is reachable with valid credentials."""
    try:
        client = IPFSClient()
        return client.is_available()
    except Exception:
        return False


@pytest.mark.skipif(not ipfs_available(), reason="Pinata API not reachable or credentials invalid")
class TestIPFSClient:

    def setup_method(self):
        self.client = IPFSClient()
        self.tmpdir = tempfile.mkdtemp(prefix="ipfs_test_")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_upload_and_download_bytes(self):
        data = pickle.dumps({"weights": [1.0, 2.0, 3.0]})
        cid = self.client.upload_bytes(data, filename="test_weights.pkl")
        assert cid  # non-empty string

        fetched = self.client.download_bytes(cid)
        assert pickle.loads(fetched) == {"weights": [1.0, 2.0, 3.0]}

    def test_upload_and_download_file(self):
        filepath = os.path.join(self.tmpdir, "model.pkl")
        weights = {"layer": [0.5, 0.6]}
        with open(filepath, "wb") as f:
            pickle.dump(weights, f)

        cid = self.client.upload_file(filepath)
        assert cid

        dest = os.path.join(self.tmpdir, "downloaded.pkl")
        self.client.download_to_file(cid, dest)
        with open(dest, "rb") as f:
            assert pickle.loads(f.read()) == weights

    def test_upload_and_download_json(self):
        obj = {"round": 5, "accuracy": 0.95}
        cid = self.client.upload_json(obj)
        assert cid

        fetched = self.client.download_json(cid)
        assert fetched == obj

    def test_pin_and_check(self):
        cid = self.client.upload_bytes(b"pin test data")
        assert self.client.is_pinned(cid)

    def test_gateway_url(self):
        url = self.client.get_gateway_url("QmTestCid123")
        assert "QmTestCid123" in url
        assert url.startswith("http")


# ═══════════════════════════════════════════════════════════════════════════
#  3.  Integration: end-to-end checkpoint round-trip via IPFS
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not ipfs_available(), reason="Pinata API not reachable or credentials invalid")
class TestEndToEndCheckpoint:
    """Simulates Peer A saving a checkpoint → IPFS → Peer B fetching it."""

    def setup_method(self):
        self.dir_a = tempfile.mkdtemp(prefix="peer_a_")
        self.dir_b = tempfile.mkdtemp(prefix="peer_b_")
        self.store_a = CheckpointStore(base_dir=self.dir_a)
        self.store_b = CheckpointStore(base_dir=self.dir_b)
        self.ipfs = IPFSClient()

    def teardown_method(self):
        shutil.rmtree(self.dir_a, ignore_errors=True)
        shutil.rmtree(self.dir_b, ignore_errors=True)

    def test_peer_a_uploads_peer_b_downloads(self):
        # Peer A trains and saves
        weights_a = {"dense": [0.1, 0.2, 0.3], "bias": [0.01]}
        self.store_a.save_checkpoint(weights_a, round_num=1, peer_id="peer-A")

        # Peer A uploads to IPFS
        data = pickle.dumps(weights_a)
        cid = self.ipfs.upload_bytes(data, filename="round_0001.pkl")

        # Peer A updates metadata with CID
        meta_path = os.path.join(self.dir_a, "round_0001", "metadata.json")
        with open(meta_path) as f:
            meta = json.load(f)
        meta["cid"] = cid
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        # ── Peer B (was offline) fetches from IPFS ──
        raw = self.ipfs.download_bytes(cid)
        weights_b = pickle.loads(raw)
        self.store_b.save_checkpoint(weights_b, round_num=1, peer_id="peer-B", cid=cid)

        # Verify
        assert weights_b == weights_a
        _, meta_b = self.store_b.load_checkpoint(1)
        assert meta_b["cid"] == cid
        assert meta_b["peer_id"] == "peer-B"

    def test_multiple_rounds_sync(self):
        """Peer A publishes 3 rounds; Peer B syncs the latest."""
        cids = {}
        for r in range(1, 4):
            w = {"round": r, "val": r * 0.1}
            self.store_a.save_checkpoint(w, round_num=r, peer_id="peer-A")
            cid = self.ipfs.upload_bytes(pickle.dumps(w))
            cids[r] = cid

        # Peer B only knows the latest CID (round 3)
        latest_cid = cids[3]
        raw = self.ipfs.download_bytes(latest_cid)
        weights = pickle.loads(raw)
        self.store_b.save_checkpoint(weights, round_num=3, peer_id="peer-B", cid=latest_cid)

        assert weights["round"] == 3
        assert self.store_b.get_latest_round() == 3


# ═══════════════════════════════════════════════════════════════════════════
#  4.  Offline peer simulation (pure persistence, no network)
# ═══════════════════════════════════════════════════════════════════════════

class TestOfflinePeerScenario:
    """
    Simulates:
      1. Peer A trains rounds 1-3 and saves checkpoints
      2. Peer B was offline – starts fresh, loads from Peer A's checkpoint dir
         (in real usage this would be from IPFS; here we test the persistence logic)
    """

    def setup_method(self):
        self.shared_dir = tempfile.mkdtemp(prefix="shared_ckpt_")
        self.store = CheckpointStore(base_dir=self.shared_dir)

    def teardown_method(self):
        shutil.rmtree(self.shared_dir, ignore_errors=True)

    def test_offline_peer_loads_latest(self):
        # Peer A saves rounds
        for r in range(1, 4):
            self.store.save_checkpoint({"acc": r * 10}, round_num=r, peer_id="A")

        # Peer B joins later and loads latest
        store_b = CheckpointStore(base_dir=self.shared_dir)
        w, meta = store_b.load_checkpoint()  # latest
        assert meta["round"] == 3
        assert w == {"acc": 30}

    def test_offline_peer_loads_specific_round(self):
        for r in [1, 5, 10]:
            self.store.save_checkpoint({"step": r}, round_num=r, peer_id="A")

        store_b = CheckpointStore(base_dir=self.shared_dir)
        w, meta = store_b.load_checkpoint(round_num=5)
        assert w == {"step": 5}
        assert meta["round"] == 5

    def test_no_checkpoint_returns_none(self):
        store_empty = CheckpointStore(base_dir=tempfile.mkdtemp())
        w, m = store_empty.load_checkpoint()
        assert w is None
        assert m is None
