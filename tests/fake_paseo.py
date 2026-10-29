#!/usr/bin/env python3
"""Stand-in for the `paseo` CLI. Records every call to $FAKE_PASEO_CALLS (one JSON argv per line)."""

import json
import os
import sys
import time

AGENTS = [
    {"id": "aaaaaaa1-0000-0000-0000-000000000001", "shortId": "aaaaaaa", "name": "alpha",
     "provider": "claude/x", "status": "running", "cwd": "~/src/a", "created": "1 days ago"},
    {"id": "bbbbbbb2-0000-0000-0000-000000000002", "shortId": "bbbbbbb", "name": "beta",
     "provider": "codex/y", "status": "idle", "cwd": "~/src/b", "created": "2 days ago"},
]

with open(os.environ["FAKE_PASEO_CALLS"], "a") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\n")

cmd = sys.argv[1]
if cmd == "ls":
    print(json.dumps(AGENTS))
elif cmd == "logs":
    tools_only = "--filter" in sys.argv
    print("[Shell] ls" if tools_only else "[User] hello there")
    if not tools_only:
        print("plain assistant line")
    sys.stdout.flush()
    time.sleep(30)  # `-f` follows until killed
elif cmd == "permit" and sys.argv[2] == "ls":
    print(os.environ.get("FAKE_PASEO_PERMITS", "[]"))
elif cmd == "send":
    if os.environ.get("FAKE_PASEO_SEND_FAIL"):
        print("boom", file=sys.stderr)
        sys.exit(1)
