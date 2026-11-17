#!/usr/bin/env python3
"""Manage the wallet statusLine: wallet addresses and the Claude Code setting.

Usage:
  setup.py add <address> [--chain CHAIN] [--name NAME]
  setup.py remove <address> [--chain CHAIN]
  setup.py list
  setup.py label <text>
  setup.py rpc <chain> <url> [<url> ...]   # override RPCs; no urls = reset to defaults
  setup.py install [--force]               # register the statusLine in ~/.claude/settings.json
  setup.py uninstall                       # remove it (restores a replaced one, if any)
  setup.py render                          # print the status line once

Only public addresses are stored. No private keys, no API keys.
Standard library only.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from statusline import CACHE_FILE, CHAINS, CONFIG_FILE, HOME_DIR  # noqa: E402

HOME = Path(HOME_DIR)
CONFIG = Path(CONFIG_FILE)
INSTALLED_SCRIPT = HOME / "statusline.py"
PREVIOUS_STATUSLINE = HOME / "previous_statusline.json"
SETTINGS = Path(os.environ.get("CLAUDE_SETTINGS_PATH") or Path.home() / ".claude" / "settings.json")

EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
SOLANA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_CHAINS = [c for c, spec in CHAINS.items() if spec["kind"] == "evm"]


def load_config():
    try:
        return json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {"label": "WALLET", "wallets": [], "rpc": {}}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def save_config(config):
    save_json(CONFIG, config)
    try:
        os.remove(CACHE_FILE)  # drop numbers for the old wallet set
    except OSError:
        pass


def detect_chain(address, chain):
    if EVM_RE.match(address):
        chain = chain or "base"
        if chain not in EVM_CHAINS:
            sys.exit(f"{address} is an EVM address; --chain must be one of: {', '.join(EVM_CHAINS)}")
        return chain, address.lower()
    if SOLANA_RE.match(address):
        if chain not in (None, "solana"):
            sys.exit(f"{address} looks like a Solana address, not {chain}")
        return "solana", address
    sys.exit(f"Not a valid EVM (0x…) or Solana address: {address}")


def cmd_add(args):
    chain, address = detect_chain(args.address.strip(), args.chain)
    config = load_config()
    wallets = config.setdefault("wallets", [])
    if any(w["chain"] == chain and w["address"] == address for w in wallets):
        print(f"Already tracked: {chain} {address}")
        return
    entry = {"chain": chain, "address": address}
    if args.name:
        entry["name"] = args.name
    wallets.append(entry)
    save_config(config)
    print(f"Added {chain} {address}")


def cmd_remove(args):
    config = load_config()
    target = args.address.strip()
    before = len(config.get("wallets", []))
    config["wallets"] = [
        w
        for w in config.get("wallets", [])
        if not (w["address"].lower() == target.lower() and (args.chain in (None, w["chain"])))
    ]
    if len(config["wallets"]) == before:
        sys.exit(f"Not tracked: {target}")
    save_config(config)
    print(f"Removed {target}")


def cmd_list(_args):
    config = load_config()
    print(f"label: {config.get('label', 'WALLET')}")
    if not config.get("wallets"):
        print("no wallets configured")
    for w in config.get("wallets", []):
        name = f"  ({w['name']})" if w.get("name") else ""
        print(f"{w['chain']:<9} {w['address']}{name}")
    for chain, urls in (config.get("rpc") or {}).items():
        print(f"rpc {chain}: {', '.join(urls)}")
    print(f"config: {CONFIG}")


def cmd_label(args):
    config = load_config()
    config["label"] = args.text
    save_json(CONFIG, config)
    print(f"Label set to {args.text!r}")


def cmd_rpc(args):
    if args.chain not in CHAINS:
        sys.exit(f"Unknown chain {args.chain}; choose from: {', '.join(CHAINS)}")
    config = load_config()
    rpc = config.setdefault("rpc", {})
    if args.urls:
        rpc[args.chain] = args.urls
        print(f"{args.chain} RPCs: {', '.join(args.urls)}")
    else:
        rpc.pop(args.chain, None)
        print(f"{args.chain} RPCs reset to defaults")
    save_json(CONFIG, config)  # balances stay valid; keep the cache


def load_settings():
    if not SETTINGS.exists():
        return {}
    try:
        return json.loads(SETTINGS.read_text())
    except ValueError:
        sys.exit(f"{SETTINGS} is not valid JSON; fix it first, nothing was changed.")


def our_command():
    return f"python3 {INSTALLED_SCRIPT}"


def cmd_install(args):
    HOME.mkdir(parents=True, exist_ok=True)
    # Copy to a stable path so updating/moving the skill never breaks settings.json.
    shutil.copy2(SCRIPT_DIR / "statusline.py", INSTALLED_SCRIPT)

    settings = load_settings()
    existing = settings.get("statusLine")
    if existing and existing.get("command") != our_command():
        if not args.force:
            sys.exit(
                f"A different statusLine is already configured in {SETTINGS}:\n  {json.dumps(existing)}\n"
                "Not overwriting it. Re-run with --force to replace it "
                "(the old one is saved and restored by `uninstall`)."
            )
        save_json(PREVIOUS_STATUSLINE, existing)

    settings["statusLine"] = {"type": "command", "command": our_command(), "refreshInterval": 30}
    save_json(SETTINGS, settings)
    print(f"statusLine installed in {SETTINGS}")
    if not load_config().get("wallets"):
        print("No wallets yet: add one with `setup.py add <address>`.")


def cmd_uninstall(_args):
    settings = load_settings()
    existing = settings.get("statusLine")
    if not existing or existing.get("command") != our_command():
        print("The wallet statusLine is not installed; nothing changed.")
        return
    if PREVIOUS_STATUSLINE.exists():
        settings["statusLine"] = json.loads(PREVIOUS_STATUSLINE.read_text())
        PREVIOUS_STATUSLINE.unlink()
        print("Restored the previous statusLine.")
    else:
        del settings["statusLine"]
    save_json(SETTINGS, settings)
    print(f"Wallet statusLine removed from {SETTINGS}. Wallet config kept in {HOME}.")


def cmd_render(_args):
    subprocess.run([sys.executable, str(SCRIPT_DIR / "statusline.py")], check=False)


def main():
    parser = argparse.ArgumentParser(description="Wallet balance status line for Claude Code")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="track a public address")
    p.add_argument("address")
    p.add_argument("--chain", choices=list(CHAINS), help="EVM chain (default: base); Solana is auto-detected")
    p.add_argument("--name")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", help="stop tracking an address")
    p.add_argument("address")
    p.add_argument("--chain", choices=list(CHAINS))
    p.set_defaults(func=cmd_remove)

    sub.add_parser("list", help="show tracked wallets").set_defaults(func=cmd_list)

    p = sub.add_parser("label", help="set the label shown before the total")
    p.add_argument("text")
    p.set_defaults(func=cmd_label)

    p = sub.add_parser("rpc", help="override RPC endpoints for a chain")
    p.add_argument("chain")
    p.add_argument("urls", nargs="*")
    p.set_defaults(func=cmd_rpc)

    p = sub.add_parser("install", help="register the statusLine in Claude Code settings")
    p.add_argument("--force", action="store_true", help="replace an existing statusLine")
    p.set_defaults(func=cmd_install)

    sub.add_parser("uninstall", help="remove the statusLine").set_defaults(func=cmd_uninstall)
    sub.add_parser("render", help="print the status line once").set_defaults(func=cmd_render)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
