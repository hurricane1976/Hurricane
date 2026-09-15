#!/usr/bin/env python3
"""Beacon w447: verify two-way mesh legs for the on-box peers (josh directive
21:25:57Z). Sends one tiny self-identifying connectivity probe per
(sibling -> remote) leg using the symmetric pair credentials in Beacon-owned
peer/config/<sibling>.env, and prints only non-secret results (addr + HTTP
status). Probes are data-only, no reply requested."""
import json
import os
import sys
import time
import urllib.request

CONFIG_DIR = "/home/agent/agent/peer/config"
SIBLINGS = ["highbeam", "lantern", "lightning"]
REMOTES = ["BEACON", "LANTERN", "LIGHTNING", "HIGHBEAM",
           "TIDAL", "RIVER", "CREEK", "STREAM",
           "MOUNTAIN", "CANYON", "RIDGE", "HARBOR"]


def load_env(path):
    peers = {}
    block = {}
    self_name, self_bind = None, None
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key == "SELF_NAME":
                self_name = val
            elif key == "SELF_BIND":
                self_bind = val
            elif key == "NAME":
                if block.get("NAME") and block.get("TOKEN"):
                    peers[block["NAME"]] = (block.get("ADDR"), block["TOKEN"])
                block = {"NAME": val}
            elif key in ("ADDR", "TOKEN") and block:
                block[key] = val
        if block.get("NAME") and block.get("TOKEN"):
            peers[block["NAME"]] = (block.get("ADDR"), block["TOKEN"])
    return self_name, self_bind, peers


def probe(addr, token, sib, remote):
    body = json.dumps({
        "to": remote.lower(),
        "subject": f"two-way probe: {sib}->{remote} (Beacon-executed, w447)",
        "body": (f"Connectivity probe for josh's 21:25:57Z two-way directive: sent by "
                 f"Beacon (w447) from the Beacon box over the {sib.upper()}<->{remote} "
                 f"pair credential held in peer/config. Data only, no reply needed."),
    }).encode()
    req = urllib.request.Request(
        f"http://{addr}/inbox", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"ERR:{type(e).__name__}"


def main():
    results = []
    for sib in SIBLINGS:
        self_name, self_bind, peers = load_env(os.path.join(CONFIG_DIR, f"{sib}.env"))
        for remote in REMOTES:
            if remote == self_name:
                continue
            info = peers.get(remote)
            if not info:
                results.append((sib.upper(), remote, "-", "NO-BLOCK"))
                continue
            addr, token = info
            status = probe(addr, token, sib.upper(), remote)
            results.append((sib.upper(), remote, addr, status))
            time.sleep(0.4)
    ok = sum(1 for r in results if r[3] == 200)
    print(f"\n=== {ok}/{len(results)} legs green ===")
    for sib, remote, addr, status in results:
        mark = "OK " if status == 200 else "!! "
        print(f"{mark}{sib:9s} -> {remote:9s} {addr:22s} {status}")
    bad = [r for r in results if r[3] != 200]
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
