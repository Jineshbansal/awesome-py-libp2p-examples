"""
demo_weights.py – Demonstrates model weight saving, loading, and inspection.

This script creates dummy neural-network-style weights, saves them through
the CheckpointStore persistence layer, and prints each step so you can
see exactly what is written to disk.

Usage:
    python demo_weights.py
"""

import json
import os
import pickle
import sys
import time
from pathlib import Path

# Make sibling modules importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "p2p_ipfs_federated"))

from persistence import CheckpointStore

# ── Formatting helpers ───────────────────────────────────────────────────

BOLD = "\033[1m"
GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
RESET = "\033[0m"

DIVIDER = "─" * 65


def banner(text: str):
    print(f"\n{BOLD}{CYAN}{'═' * 65}")
    print(f"  {text}")
    print(f"{'═' * 65}{RESET}\n")


def section(text: str):
    print(f"\n{YELLOW}{DIVIDER}")
    print(f"  {text}")
    print(f"{DIVIDER}{RESET}")


# ── Simulated model weights ─────────────────────────────────────────────

def make_dummy_weights(round_num: int) -> dict:
    """
    Create fake weights that change every round so you can see
    how values evolve when saved and reloaded.
    """
    import random
    random.seed(round_num)  # deterministic per round
    return {
        "conv1.weight": [round(random.gauss(0, 0.5), 6) for _ in range(6)],
        "conv1.bias":   [round(random.gauss(0, 0.1), 6) for _ in range(3)],
        "fc1.weight":   [round(random.gauss(0, 0.3), 6) for _ in range(8)],
        "fc1.bias":     [round(random.gauss(0, 0.05), 6) for _ in range(4)],
        "fc2.weight":   [round(random.gauss(0, 0.2), 6) for _ in range(4)],
        "fc2.bias":     [round(random.gauss(0, 0.01), 6) for _ in range(2)],
    }


def print_weights(weights: dict, label: str = "Weights"):
    """Pretty-print a weights dictionary."""
    print(f"\n  {BOLD}{label}:{RESET}")
    for layer_name, values in weights.items():
        truncated = values[:5]
        suffix = f"  … ({len(values)} params)" if len(values) > 5 else f"  ({len(values)} params)"
        print(f"    {GREEN}{layer_name:20s}{RESET} → {truncated}{suffix}")


# ── Main demo ───────────────────────────────────────────────────────────

def main():
    checkpoint_dir = "./demo_checkpoints"

    banner("P2P + IPFS  ·  Weight Saving Demo")

    # Clean previous demo run
    if Path(checkpoint_dir).exists():
        import shutil
        shutil.rmtree(checkpoint_dir)
        print(f"  🗑  Cleaned previous demo directory: {checkpoint_dir}\n")

    store = CheckpointStore(base_dir=checkpoint_dir)
    print(f"  📂 Checkpoint directory: {BOLD}{Path(checkpoint_dir).resolve()}{RESET}")

    total_rounds = 5
    peer_id = "demo-peer-001"

    # ── 1. Save weights for several rounds ───────────────────────────────

    section("STEP 1 ▸ Saving weights for 5 training rounds")

    for r in range(1, total_rounds + 1):
        weights = make_dummy_weights(r)

        print(f"\n  🔄 Round {r}: generating weights …")
        print_weights(weights, label=f"Round {r} weights")

        saved_dir = store.save_checkpoint(
            weights=weights,
            round_num=r,
            peer_id=peer_id,
            cid=f"QmFakeCID_round{r}",
        )

        # Show what was written to disk
        weights_file = saved_dir / "weights.pkl"
        meta_file = saved_dir / "metadata.json"
        w_size = weights_file.stat().st_size
        m_size = meta_file.stat().st_size

        print(f"  💾 Saved → {MAGENTA}{saved_dir}{RESET}")
        print(f"     weights.pkl   : {w_size:,} bytes")
        print(f"     metadata.json : {m_size:,} bytes")

        # Print the metadata content
        with open(meta_file) as f:
            meta = json.load(f)
        print(f"     metadata      : round={meta['round']}, peer={meta['peer_id']}, cid={meta['cid']}")

        time.sleep(0.15)  # small delay so output feels sequential

    # ── 2. List all saved rounds ─────────────────────────────────────────

    section("STEP 2 ▸ Listing all saved rounds on disk")

    rounds = store.list_rounds()
    print(f"\n  📋 Rounds stored: {rounds}")
    print(f"  📌 Latest round : {store.get_latest_round()}")
    print(f"  🔗 Latest CID   : {store.get_latest_cid()}")

    # ── 3. Reload specific rounds and verify ─────────────────────────────

    section("STEP 3 ▸ Reloading weights from disk")

    for r in [1, 3, 5]:
        loaded_weights, meta = store.load_checkpoint(r)
        original = make_dummy_weights(r)
        match = loaded_weights == original
        status = f"{GREEN}✓ MATCH{RESET}" if match else f"\033[91m✗ MISMATCH{RESET}"

        print(f"\n  🔍 Round {r}: {status}")
        print_weights(loaded_weights, label=f"Loaded round {r}")

    # ── 4. Load latest (no round specified) ──────────────────────────────

    section("STEP 4 ▸ Loading the latest checkpoint (no round specified)")

    latest_w, latest_m = store.load_checkpoint()
    print(f"\n  📌 Loaded round: {latest_m['round']}")
    print_weights(latest_w, label="Latest weights")

    # ── 5. Inspect raw pickle bytes ──────────────────────────────────────

    section("STEP 5 ▸ Inspecting the raw pickle file")

    pkl_path = Path(checkpoint_dir) / "round_0005" / "weights.pkl"
    raw_size = pkl_path.stat().st_size
    print(f"\n  📦 File: {pkl_path}")
    print(f"  📏 Size: {raw_size:,} bytes")

    with open(pkl_path, "rb") as f:
        raw_bytes = f.read()

    print(f"  🔎 First 80 bytes (hex): {raw_bytes[:80].hex()}")

    reloaded = pickle.loads(raw_bytes)
    print(f"  ✅ Deserialized keys: {list(reloaded.keys())}")
    print(f"  ✅ Total parameters : {sum(len(v) for v in reloaded.values())}")

    # ── 6. Prune old checkpoints ─────────────────────────────────────────

    section("STEP 6 ▸ Pruning – keep only last 2 rounds")

    print(f"\n  Before prune: {store.list_rounds()}")
    store.prune(keep_last=2)
    print(f"  After prune : {store.list_rounds()}")

    # ── 7. Directory tree ────────────────────────────────────────────────

    section("STEP 7 ▸ Final directory tree")

    for root, dirs, files in os.walk(checkpoint_dir):
        level = root.replace(checkpoint_dir, "").count(os.sep)
        indent = "  " + "  │ " * level
        print(f"{indent}📁 {os.path.basename(root)}/")
        sub_indent = "  " + "  │ " * (level + 1)
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            size = os.path.getsize(fpath)
            print(f"{sub_indent}📄 {fname}  ({size:,} B)")

    # ── Done ─────────────────────────────────────────────────────────────

    banner("Demo complete – weights were saved, loaded, verified & pruned")


if __name__ == "__main__":
    main()
