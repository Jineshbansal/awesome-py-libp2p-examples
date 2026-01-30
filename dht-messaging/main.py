"""Small CLI wrapper to run the examples or send a single message.

Usage examples:
  - Start an interactive server/node (same as `pair.py`):
      python -m dht_messaging.main run-server

  - Send a single message to a peer resolved via the DHT:
      python -m dht_messaging.main send -t <peerid> -m "hello"

This file keeps the surface small and re-uses existing module CLIs.
"""
import argparse
import runpy
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Helper CLI for dht-messaging examples")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run-server", help="Run an interactive server node (pair.py)")

    send_p = sub.add_parser("send", help="Send one message to a peer via the DHT")
    send_p.add_argument("-t", "--target-peer-id", required=True)
    send_p.add_argument("-m", "--message", required=True)
    send_p.add_argument("-p", "--port", type=int, default=0)

    args = parser.parse_args()

    if args.cmd == "run-server":
        # Execute the pair.py script in this folder
        runpy.run_path(str(ROOT / "pair.py"), run_name="__main__")
    elif args.cmd == "send":
        # Call chat.py as a subprocess so that its CLI runs in a clean process
        cmd = [sys.executable, str(ROOT / "chat.py"), "-t", args.target_peer_id, "-m", args.message]
        if args.port:
            cmd += ["-p", str(args.port)]
        subprocess.run(cmd)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
