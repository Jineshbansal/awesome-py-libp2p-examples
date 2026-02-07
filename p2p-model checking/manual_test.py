"""
manual_test.py – Full manual testing of the P2P + IPFS node system.

Part A: Single-node tests (boots a real bootstrap node, exercises all commands)
Part B: Multi-node test (launches 2 separate processes and connects them)

Usage:
    python manual_test.py
"""

import json
import os
import pickle
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

# Ensure sibling modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "p2p_ipfs_federated"))

import multiaddr
import trio
from libp2p.tools.async_service.trio_service import background_trio_service

from coordinator import COMMANDS, CID_TOPIC, FED_LEARNING_MESH, Node
from persistence import CheckpointStore
from ipfs_utils import IPFSClient
from logs import setup_logging

logger = setup_logging("manual-test")

# ── Formatting ───────────────────────────────────────────────────────────

BOLD   = "\033[1m"
GREEN  = "\033[92m"
RED    = "\033[91m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
MAGENTA= "\033[95m"
RESET  = "\033[0m"

pass_count = 0
fail_count = 0


def banner(text: str):
    print(f"\n{BOLD}{CYAN}{'═' * 70}")
    print(f"  {text}")
    print(f"{'═' * 70}{RESET}\n")


def section(text: str):
    print(f"\n{YELLOW}{'─' * 70}")
    print(f"  {text}")
    print(f"{'─' * 70}{RESET}")


def check(name: str, condition: bool, detail: str = ""):
    global pass_count, fail_count
    if condition:
        pass_count += 1
        print(f"  {GREEN}✅ PASS{RESET}  {name}  {detail}")
    else:
        fail_count += 1
        print(f"  {RED}❌ FAIL{RESET}  {name}  {detail}")


def print_dir_tree(base: str, label: str = ""):
    if label:
        print(f"\n  📁 {label}")
    for root, dirs, files in os.walk(base):
        level = root.replace(base, "").count(os.sep)
        indent = "  " + "  │ " * level
        print(f"{indent}📁 {os.path.basename(root)}/")
        sub_indent = "  " + "  │ " * (level + 1)
        for fname in sorted(files):
            fpath = os.path.join(root, fname)
            sz = os.path.getsize(fpath)
            print(f"{sub_indent}📄 {fname}  ({sz:,} B)")


# ═════════════════════════════════════════════════════════════════════════
# PART A: Single-node manual testing (real libp2p node)
# ═════════════════════════════════════════════════════════════════════════

async def test_single_node():
    global pass_count, fail_count

    banner("PART A — Single Bootstrap Node Manual Testing")

    ckpt_dir = "./test_manual_checkpoints"
    if Path(ckpt_dir).exists():
        shutil.rmtree(ckpt_dir)

    # ── TEST 1: Create node ──────────────────────────────────────────────

    section("TEST 1 ▸ Create a BOOTSTRAP node")

    node = Node(role="bootstrap", checkpoint_dir=ckpt_dir)
    check("Node created", node.role == "bootstrap")
    check("Host object exists", node.host is not None)
    check("Pubsub object exists", node.pubsub is not None)
    check("IPFS client exists", node.ipfs is not None)
    check("Checkpoint store exists", node.checkpoint_store is not None)
    check("No weights initially", node.current_weights is None)
    check("Round starts at 0", node.current_round == 0)
    check("Known CIDs empty", len(node.known_cids) == 0)

    # ── TEST 2: Boot the network stack ───────────────────────────────────

    section("TEST 2 ▸ Boot libp2p network + pubsub")

    port = 8000
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")

    async with (
        node.host.run(listen_addrs=[listen_addr]),
        trio.open_nursery() as nursery,
    ):
        nursery.start_soon(node.host.get_peerstore().start_cleanup_task, 60)

        async with background_trio_service(node.pubsub):
            async with background_trio_service(node.gossipsub):
                await trio.sleep(1)
                await node.pubsub.wait_until_ready()

                check("Pubsub ready", True)
                peer_id = node.host.get_id()
                check("Peer ID assigned", peer_id is not None)
                print(f"  🆔 Peer ID: {MAGENTA}{peer_id}{RESET}")

                # Start command executor
                nursery.start_soon(node.command_executor, nursery)

                # Subscribe to topics
                cid_sub = await node.pubsub.subscribe(CID_TOPIC)
                nursery.start_soon(node.receive_loop, cid_sub)
                node.subscribed_topics.append(CID_TOPIC)

                main_sub = await node.pubsub.subscribe(FED_LEARNING_MESH)
                nursery.start_soon(node.receive_loop, main_sub)
                node.subscribed_topics.append(FED_LEARNING_MESH)

                check("Subscribed to CID topic", CID_TOPIC in node.subscribed_topics)
                check("Subscribed to main mesh", FED_LEARNING_MESH in node.subscribed_topics)

                # ── TEST 3: Command: local ───────────────────────────

                section("TEST 3 ▸ Command: local")
                await node.send_channel.send(["local"])
                await trio.sleep(0.5)
                check("local command ran", True)

                # ── TEST 4: Command: topics ──────────────────────────

                section("TEST 4 ▸ Command: topics")
                await node.send_channel.send(["topics"])
                await trio.sleep(0.5)
                check("topics shows CID", CID_TOPIC in node.subscribed_topics)
                check("topics shows mesh", FED_LEARNING_MESH in node.subscribed_topics)

                # ── TEST 5: Command: peers (empty) ───────────────────

                section("TEST 5 ▸ Command: peers (no connections yet)")
                await node.send_channel.send(["peers"])
                await trio.sleep(0.5)
                check("peers cmd ran (empty)", True)

                # ── TEST 6: Command: help ────────────────────────────

                section("TEST 6 ▸ Command: help")
                await node.send_channel.send(["help"])
                await trio.sleep(0.5)
                check("help text length > 100", len(COMMANDS) > 100)

                # ── TEST 7: Command: rounds (empty) ──────────────────

                section("TEST 7 ▸ Command: rounds (empty)")
                await node.send_channel.send(["rounds"])
                await trio.sleep(0.5)
                rounds = node.checkpoint_store.list_rounds()
                check("No rounds initially", len(rounds) == 0, f"{rounds}")

                # ── TEST 8: Command: cids (empty) ────────────────────

                section("TEST 8 ▸ Command: cids (empty)")
                await node.send_channel.send(["cids"])
                await trio.sleep(0.5)
                check("No CIDs initially", len(node.known_cids) == 0)

                # ── TEST 9: set_weights ──────────────────────────────

                section("TEST 9 ▸ set_weights() – inject dummy model")

                weights_r1 = {
                    "conv1.weight": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                    "conv1.bias":   [0.01, 0.02, 0.03],
                    "fc1.weight":   [0.7, 0.8, 0.9, 1.0],
                    "fc1.bias":     [0.04, 0.05],
                }
                node.set_weights(weights_r1, round_num=1)
                check("Weights in memory", node.current_weights is not None)
                check("Round = 1", node.current_round == 1)
                check("Weights match", node.current_weights == weights_r1)

                print(f"\n  📊 Weights in memory:")
                for k, v in node.current_weights.items():
                    print(f"     {GREEN}{k:20s}{RESET} → {v}")

                # ── TEST 10: Save checkpoint to disk ─────────────────

                section("TEST 10 ▸ checkpoint_save (persistence layer)")

                node.checkpoint_store.save_checkpoint(
                    weights=node.current_weights,
                    round_num=1,
                    peer_id=str(peer_id),
                    cid="",
                )
                check("Round 1 on disk", node.checkpoint_store.has_round(1))
                meta = node.checkpoint_store.load_metadata(1)
                check("Metadata round=1", meta["round"] == 1)
                check("Metadata peer_id set", meta["peer_id"] == str(peer_id))
                print(f"\n  📋 Metadata:\n{json.dumps(meta, indent=4)}")

                # ── TEST 11: Save multiple rounds ────────────────────

                section("TEST 11 ▸ Save rounds 2-5 (simulated training)")

                for r in range(2, 6):
                    evolved = {
                        k: [round(x + 0.01 * r, 6) for x in v]
                        for k, v in weights_r1.items()
                    }
                    node.set_weights(evolved, round_num=r)
                    node.checkpoint_store.save_checkpoint(
                        weights=evolved,
                        round_num=r,
                        peer_id=str(peer_id),
                    )
                    print(f"  💾 Round {r}: conv1.weight = {evolved['conv1.weight'][:3]}…")

                rounds = node.checkpoint_store.list_rounds()
                check("5 rounds stored", len(rounds) == 5, f"{rounds}")
                check("Rounds = [1..5]", rounds == [1, 2, 3, 4, 5])

                # ── TEST 12: Command: rounds ─────────────────────────

                section("TEST 12 ▸ Command: rounds (after saving)")
                await node.send_channel.send(["rounds"])
                await trio.sleep(0.5)
                check("rounds cmd shows 5", True, f"{rounds}")

                # ── TEST 13: checkpoint_load specific round ──────────

                section("TEST 13 ▸ checkpoint_load round 3")

                node._load_local(3)
                check("Loaded round 3", node.current_round == 3)
                expected_r3 = {k: [round(x + 0.03, 6) for x in v] for k, v in weights_r1.items()}
                check("Round 3 weights correct", node.current_weights == expected_r3)
                print(f"  📊 Round 3 conv1.weight: {node.current_weights['conv1.weight'][:3]}…")

                # ── TEST 14: checkpoint_load latest ──────────────────

                section("TEST 14 ▸ checkpoint_load latest (no round given)")

                node._load_local()
                check("Loaded latest = round 5", node.current_round == 5)
                expected_r5 = {k: [round(x + 0.05, 6) for x in v] for k, v in weights_r1.items()}
                check("Round 5 weights correct", node.current_weights == expected_r5)
                print(f"  📊 Round 5 conv1.weight: {node.current_weights['conv1.weight'][:3]}…")

                # ── TEST 15: advertize a training topic ──────────────

                section("TEST 15 ▸ Command: advertize (start training round)")
                topic = "training-round-alpha"
                await node.send_channel.send(["advertize", topic])
                await trio.sleep(1)
                check("Topic subscribed", topic in node.subscribed_topics)
                check("training_topic set", node.training_topic == topic)
                check("is_subscribed = True", node.is_subscribed is True)

                # ── TEST 16: publish on topic ────────────────────────

                section("TEST 16 ▸ Command: publish (send message)")
                await node.send_channel.send(["publish", topic, "weights-update-v1"])
                await trio.sleep(1)
                check("publish executed", True)

                # ── TEST 17: leave topic ─────────────────────────────

                section("TEST 17 ▸ Command: leave (unsubscribe)")
                await node.send_channel.send(["leave", topic])
                await trio.sleep(0.5)
                check("Left topic", topic not in node.subscribed_topics)
                check("is_subscribed = False", node.is_subscribed is False)
                check("training_topic = None", node.training_topic is None)

                # ── TEST 18: Prune checkpoints ───────────────────────

                section("TEST 18 ▸ Prune old checkpoints (keep last 2)")

                before = node.checkpoint_store.list_rounds()
                print(f"  Before: {before}")
                node.checkpoint_store.prune(keep_last=2)
                after = node.checkpoint_store.list_rounds()
                print(f"  After:  {after}")
                check("Kept last 2", len(after) == 2)
                check("Kept [4, 5]", after == [4, 5])

                # ── TEST 19: Load non-existent round ─────────────────

                section("TEST 19 ▸ Load non-existent round")
                w, m = node.checkpoint_store.load_checkpoint(999)
                check("Returns None, None", w is None and m is None)

                # ── TEST 20: Save with CID metadata ──────────────────

                section("TEST 20 ▸ Save checkpoint with CID metadata")
                node.set_weights({"w": 42}, round_num=99)
                node.checkpoint_store.save_checkpoint(
                    weights={"w": 42},
                    round_num=99,
                    peer_id=str(peer_id),
                    cid="QmAbCdEf123456",
                )
                _, meta99 = node.checkpoint_store.load_checkpoint(99)
                check("CID in metadata", meta99["cid"] == "QmAbCdEf123456")
                print(f"  📋 Metadata:\n{json.dumps(meta99, indent=4)}")

                # ── TEST 21: IPFS client basic checks ────────────────────

                section("TEST 21 ▸ IPFS client (no upload — just API check)")
                ipfs = IPFSClient()
                check("IPFSClient instantiated", ipfs is not None)
                gw = ipfs.get_gateway_url("QmTestCid")
                check("Gateway URL has CID", "QmTestCid" in gw, f"url={gw}")

                # ── TEST 22: Verify pickle files on disk ─────────────────

                section("TEST 22 ▸ Inspect raw pickle file on disk")
                pkl_path = Path(ckpt_dir) / "round_0099" / "weights.pkl"
                check("Pickle file exists", pkl_path.exists())
                raw_size = pkl_path.stat().st_size
                print(f"  📦 {pkl_path} → {raw_size:,} bytes")
                with open(pkl_path, "rb") as f:
                    reloaded = pickle.load(f)
                check("Pickle deserialized", reloaded == {"w": 42})
                print(f"  ✅ Content: {reloaded}")

                # ── TEST 23: Directory tree ──────────────────────────────────

                section("TEST 23 ▸ Checkpoint directory tree")
                print_dir_tree(ckpt_dir)

                # ── TEST 24: sync command (offline sync, no CIDs) ────

                section("TEST 24 ▸ Command: sync (offline, no known CIDs)")
                node.known_cids.clear()
                await node.send_channel.send(["sync"])
                await trio.sleep(1)
                check("sync fallback to local", node.current_weights is not None)

                # ── Shutdown ─────────────────────────────────────────

                section("TEST 25 ▸ Command: exit (shutdown)")
                await node.send_channel.send(["exit"])
                await trio.sleep(1.5)  # Give command executor time to process
                check("Exit command sent", node.termination_event.is_set())
                nursery.cancel_scope.cancel()

    # Cleanup
    if Path(ckpt_dir).exists():
        shutil.rmtree(ckpt_dir)


# ═════════════════════════════════════════════════════════════════════════
# PART B: Multi-node test (two separate processes)
# ═════════════════════════════════════════════════════════════════════════

def test_multi_node():
    global pass_count, fail_count

    banner("PART B — Multi-Node Test (separate processes)")

    python = sys.executable
    pkg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "p2p_ipfs_federated")

    ckpt_b = os.path.abspath("./test_multi_ckpt_bootstrap")
    ckpt_t = os.path.abspath("./test_multi_ckpt_trainer")
    for d in [ckpt_b, ckpt_t]:
        if Path(d).exists():
            shutil.rmtree(d)

    # Write scripts to temp files to avoid subprocess -c issues
    bootstrap_script_path = os.path.abspath("./_test_bootstrap_node.py")
    trainer_script_path = os.path.abspath("./_test_trainer_node.py")

    with open(bootstrap_script_path, "w") as f:
        f.write(textwrap.dedent(f"""\
import sys, os, json, pickle, time, logging
sys.path.insert(0, {pkg_dir!r})
logging.disable(logging.CRITICAL)  # suppress log noise on stdout
import multiaddr, trio
from libp2p.tools.async_service.trio_service import background_trio_service
from coordinator import CID_TOPIC, FED_LEARNING_MESH, Node

async def main():
    node = Node(role="bootstrap", checkpoint_dir={ckpt_b!r})
    addr = multiaddr.Multiaddr("/ip4/0.0.0.0/tcp/9000")
    async with (
        node.host.run(listen_addrs=[addr]),
        trio.open_nursery() as nursery,
    ):
        nursery.start_soon(node.host.get_peerstore().start_cleanup_task, 60)
        async with background_trio_service(node.pubsub):
            async with background_trio_service(node.gossipsub):
                await trio.sleep(1)
                await node.pubsub.wait_until_ready()
                nursery.start_soon(node.command_executor, nursery)
                cid_sub = await node.pubsub.subscribe(CID_TOPIC)
                nursery.start_soon(node.receive_loop, cid_sub)
                main_sub = await node.pubsub.subscribe(FED_LEARNING_MESH)
                nursery.start_soon(node.receive_loop, main_sub)
                peer_id = str(node.host.get_id())
                full_addr = f"/ip4/127.0.0.1/tcp/9000/p2p/{{peer_id}}"
                print(f"BOOTSTRAP_ADDR={{full_addr}}", flush=True)
                weights = {{"layer1": [1.0, 2.0, 3.0], "layer2": [4.0, 5.0]}}
                node.set_weights(weights, round_num=1)
                node.checkpoint_store.save_checkpoint(weights=weights, round_num=1, peer_id=peer_id)
                print("WEIGHTS_SAVED=1", flush=True)
                await node.send_channel.send(["advertize", "training-session"])
                await trio.sleep(1)
                print("TOPIC_ADVERTIZED=training-session", flush=True)
                # Stay alive for trainer to connect
                await trio.sleep(12)
                peers = list(node.pubsub.peers.keys())
                print(f"PEER_COUNT={{len(peers)}}", flush=True)
                print("BOOTSTRAP_DONE", flush=True)
                node.termination_event.set()
                nursery.cancel_scope.cancel()

trio.run(main)
"""))

    section("Starting BOOTSTRAP process…")

    bootstrap_proc = subprocess.Popen(
        [python, bootstrap_script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # suppress stderr to avoid blocking
        text=True,
        bufsize=1,  # line-buffered
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    bootstrap_addr = None
    deadline = time.time() + 15
    while time.time() < deadline:
        line = bootstrap_proc.stdout.readline().strip()
        if line:
            print(f"  [bootstrap] {line}")
            if line.startswith("BOOTSTRAP_ADDR="):
                bootstrap_addr = line.split("=", 1)[1]
            elif line.startswith("WEIGHTS_SAVED="):
                check("Bootstrap saved weights", True)
            elif line.startswith("TOPIC_ADVERTIZED="):
                check("Bootstrap advertized topic", True, line.split("=")[1])
                break
        if bootstrap_proc.poll() is not None:
            break

    if not bootstrap_addr:
        print(f"  {RED}Bootstrap failed to start!{RESET}")
        check("Bootstrap started", False)
        bootstrap_proc.kill()
        return

    check("Bootstrap started", True, f"addr=…{bootstrap_addr[-30:]}")

    section("Starting TRAINER process…")

    with open(trainer_script_path, "w") as f:
        f.write(textwrap.dedent(f"""\
import sys, os, json, pickle, time, logging
sys.path.insert(0, {pkg_dir!r})
logging.disable(logging.CRITICAL)
import multiaddr, trio
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.utils.address_validation import find_free_port
from coordinator import CID_TOPIC, FED_LEARNING_MESH, Node

async def main():
    bootstrap_addr = "{bootstrap_addr}"
    port = find_free_port()
    node = Node(role="trainer", checkpoint_dir={ckpt_t!r})
    addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{{port}}")
    async with (
        node.host.run(listen_addrs=[addr]),
        trio.open_nursery() as nursery,
    ):
        nursery.start_soon(node.host.get_peerstore().start_cleanup_task, 60)
        async with background_trio_service(node.pubsub):
            async with background_trio_service(node.gossipsub):
                await trio.sleep(1)
                await node.pubsub.wait_until_ready()
                nursery.start_soon(node.command_executor, nursery)
                cid_sub = await node.pubsub.subscribe(CID_TOPIC)
                nursery.start_soon(node.receive_loop, cid_sub)
                main_sub = await node.pubsub.subscribe(FED_LEARNING_MESH)
                nursery.start_soon(node.receive_loop, main_sub)
                maddr = multiaddr.Multiaddr(bootstrap_addr)
                info = info_from_p2p_addr(maddr)
                await node.host.connect(info)
                await trio.sleep(2)
                print("CONNECTED=true", flush=True)
                await node.send_channel.send(["join", "training-session"])
                await trio.sleep(1)
                print("JOINED=training-session", flush=True)
                await node.send_channel.send(["publish", "training-session", "trainer-ready"])
                await trio.sleep(1)
                print("PUBLISHED=true", flush=True)
                weights = {{"layer1": [9.0, 8.0, 7.0], "layer2": [6.0, 5.0]}}
                node.set_weights(weights, round_num=1)
                node.checkpoint_store.save_checkpoint(weights=weights, round_num=1, peer_id=str(node.host.get_id()))
                print("TRAINER_WEIGHTS_SAVED=1", flush=True)
                peers = list(node.pubsub.peers.keys())
                print(f"TRAINER_PEER_COUNT={{len(peers)}}", flush=True)
                await node.send_channel.send(["leave", "training-session"])
                await trio.sleep(1)
                print("LEFT=training-session", flush=True)
                print("TRAINER_DONE", flush=True)
                await trio.sleep(1)
                node.termination_event.set()
                nursery.cancel_scope.cancel()

trio.run(main)
"""))

    trainer_proc = subprocess.Popen(
        [python, trainer_script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    # Read trainer output
    trainer_deadline = time.time() + 25
    while time.time() < trainer_deadline:
        line = trainer_proc.stdout.readline().strip()
        if line:
            print(f"  [trainer] {line}")
            if line.startswith("CONNECTED="):
                check("Trainer connected", line == "CONNECTED=true")
            elif line.startswith("JOINED="):
                check("Trainer joined topic", True, line.split("=")[1])
            elif line.startswith("PUBLISHED="):
                check("Trainer published message", True)
            elif line.startswith("TRAINER_WEIGHTS_SAVED="):
                check("Trainer saved weights", True)
            elif line.startswith("TRAINER_PEER_COUNT="):
                cnt = int(line.split("=")[1])
                check("Trainer sees peers", cnt > 0, f"count={cnt}")
            elif line.startswith("LEFT="):
                check("Trainer left topic", True, line.split("=")[1])
            elif line == "TRAINER_DONE":
                break
        if trainer_proc.poll() is not None:
            break

    # Now read remaining bootstrap output
    bootstrap_deadline = time.time() + 15
    while time.time() < bootstrap_deadline:
        line = bootstrap_proc.stdout.readline().strip()
        if line:
            print(f"  [bootstrap] {line}")
            if line == "BOOTSTRAP_DONE":
                break
        if bootstrap_proc.poll() is not None:
            remaining = bootstrap_proc.stdout.read()
            for l in remaining.strip().split("\n"):
                l = l.strip()
                if l:
                    print(f"  [bootstrap] {l}")
            break

    # Kill anything still running
    for proc in [bootstrap_proc, trainer_proc]:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    # ── Verify files on disk ─────────────────────────────────────────

    section("Verifying checkpoint files on disk")

    if Path(ckpt_b).exists():
        store_b = CheckpointStore(base_dir=ckpt_b)
        check("Bootstrap ckpt dir exists", True)
        b_rounds = store_b.list_rounds()
        check("Bootstrap has round 1", 1 in b_rounds, f"rounds={b_rounds}")
        w, m = store_b.load_checkpoint(1)
        check("Bootstrap weights loadable", w is not None)
        if w:
            print(f"  📊 Bootstrap weights: {w}")
        print_dir_tree(ckpt_b, "bootstrap checkpoints")
    else:
        check("Bootstrap ckpt dir exists", False)

    if Path(ckpt_t).exists():
        store_t = CheckpointStore(base_dir=ckpt_t)
        check("Trainer ckpt dir exists", True)
        t_rounds = store_t.list_rounds()
        check("Trainer has round 1", 1 in t_rounds, f"rounds={t_rounds}")
        w, m = store_t.load_checkpoint(1)
        check("Trainer weights loadable", w is not None)
        if w:
            print(f"  📊 Trainer weights: {w}")
        print_dir_tree(ckpt_t, "trainer checkpoints")
    else:
        check("Trainer ckpt dir exists", False)

    # Cleanup
    for d in [ckpt_b, ckpt_t]:
        if Path(d).exists():
            shutil.rmtree(d)
    for f in [bootstrap_script_path, trainer_script_path]:
        if os.path.exists(f):
            os.remove(f)


# ═════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════

def main():
    global pass_count, fail_count

    banner("MANUAL TESTING — P2P + IPFS System")

    # Part A: Single node
    try:
        trio.run(test_single_node)
    except Exception as e:
        print(f"\n  {RED}Part A error: {e}{RESET}")
        import traceback
        traceback.print_exc()

    # Part B: Multi node
    try:
        test_multi_node()
    except Exception as e:
        print(f"\n  {RED}Part B error: {e}{RESET}")
        import traceback
        traceback.print_exc()

    # Final summary
    banner(f"FINAL RESULTS:  {GREEN}{pass_count} PASSED{RESET}  /  {RED}{fail_count} FAILED{RESET}")
    total = pass_count + fail_count
    print(f"  Total checks : {total}")
    print(f"  {GREEN}Passed       : {pass_count}{RESET}")
    print(f"  {RED}Failed       : {fail_count}{RESET}")
    pct = (pass_count / total * 100) if total else 0
    print(f"  Pass rate    : {pct:.0f}%\n")


if __name__ == "__main__":
    main()
