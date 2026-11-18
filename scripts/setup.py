#!/usr/bin/env python3
"""Manage the wallet statusLine: wallet addresses and the Claude Code setting.

Usage:
  setup.py add <address> [--chain CHAIN] [--name NAME]
  setup.py remove <address> [--chain CHAIN]
  setup.py list
  setup.py label <text>
  setup.py asset add usdc|native|<contract> [--chain CHAIN|*] [--symbol S] [--decimals N] [--stable]
  setup.py asset remove usdc|native|<contract> [--chain CHAIN|*]
  setup.py display auto|asset|chain|none   # breakdown shown after the total
  setup.py status [--json]                 # wallets, tracked assets, untracked options
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
from statusline import (  # noqa: E402
    CHAINS,
    CONFIG_FILE,
    DEFAULT_ASSETS,
    HOME_DIR,
    fetch_prices,
    resolve_assets,
    near_view,
    rpc_with_fallback,
    wallet_chains,
)

HOME = Path(HOME_DIR)
CONFIG = Path(CONFIG_FILE)
INSTALLED_SCRIPT = HOME / "statusline.py"
PREVIOUS_STATUSLINE = HOME / "previous_statusline.json"
SETTINGS = Path(os.environ.get("CLAUDE_SETTINGS_PATH") or Path.home() / ".claude" / "settings.json")

EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
SOLANA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
# NEAR account ids: implicit (64 hex) or named (alice.near, x.tg). Top-level names
# without a dot and ETH-implicit 0x… accounts need an explicit --chain near.
NEAR_RE = re.compile(r"^(?=.{2,64}$)([a-z\d]+[-_])*[a-z\d]+(\.([a-z\d]+[-_])*[a-z\d]+)*$")
NEAR_IMPLICIT_RE = re.compile(r"^[0-9a-f]{64}$")


def looks_like_near(address):
    return bool(NEAR_IMPLICIT_RE.match(address) or ("." in address and NEAR_RE.match(address)))
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
    sync_installed_script()


def sync_installed_script():
    """Keep the installed copy in step with this skill version (e.g. after `git pull`)."""
    src = SCRIPT_DIR / "statusline.py"
    if INSTALLED_SCRIPT.exists() and INSTALLED_SCRIPT.read_bytes() != src.read_bytes():
        shutil.copy2(src, INSTALLED_SCRIPT)


def detect_chain(address, chain):
    if chain == "near":
        address = address.lower()
        if not NEAR_RE.match(address):
            sys.exit(f"Not a valid NEAR account id: {address}")
        return "near", address
    if EVM_RE.match(address):
        chain = chain or "base"
        if chain not in EVM_CHAINS:
            sys.exit(f"{address} is an EVM address; --chain must be one of: {', '.join(EVM_CHAINS)}")
        return chain, address.lower()
    if SOLANA_RE.match(address):
        if chain not in (None, "solana"):
            sys.exit(f"{address} looks like a Solana address, not {chain}")
        return "solana", address
    if looks_like_near(address.lower()):
        return "near", address.lower()
    sys.exit(f"Not a valid EVM (0x…), Solana or NEAR address: {address}")


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
    print(f"display: {config.get('display', 'auto')}")
    print("assets:")
    for e in config.get("assets", DEFAULT_ASSETS):
        what = e["kind"] if e["kind"] != "token" else f"{e.get('symbol')} {e['address']}"
        print(f"  {e['chain']:<9} {what}")
    for chain, urls in (config.get("rpc") or {}).items():
        print(f"rpc {chain}: {', '.join(urls)}")
    print(f"config: {CONFIG}")


def cmd_label(args):
    config = load_config()
    config["label"] = args.text
    save_config(config)
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
    save_config(config)


# ---------------------------------------------------------------- assets

def evm_string(raw):
    """Decode an ABI string (or bytes32) return value."""
    b = bytes.fromhex(raw[2:]) if raw and raw != "0x" else b""
    if len(b) >= 96:
        length = int.from_bytes(b[32:64], "big")
        b = b[64:64 + length]
    return b.rstrip(b"\0").decode("utf-8", "ignore").strip()


def token_metadata(config, chain, address):
    """Symbol + decimals for a contract/mint: DeFiLlama first, then the chain itself."""
    meta = {}
    try:
        info = fetch_prices({f"{CHAINS[chain]['llama']}:{address}"})
        meta = next(iter(info.values()), {})
    except Exception:
        pass
    symbol, decimals = meta.get("symbol"), meta.get("decimals")
    rpcs = (config.get("rpc") or {}).get(chain) or CHAINS[chain]["rpcs"]
    if CHAINS[chain]["kind"] == "near":
        if decimals is None or not symbol:
            try:
                ft = near_view(rpcs, address, "ft_metadata", {})
            except Exception as err:
                raise ValueError(f"{address} is not a NEAR fungible token ({err})")
            symbol = symbol or ft.get("symbol")
            decimals = ft.get("decimals") if decimals is None else decimals
    elif CHAINS[chain]["kind"] == "solana":
        if decimals is None:
            acc = rpc_with_fallback(rpcs, "getAccountInfo", [address, {"encoding": "jsonParsed"}])["value"]
            parsed = (acc or {}).get("data", {})
            parsed = parsed.get("parsed") if isinstance(parsed, dict) else None
            if not parsed or parsed.get("type") != "mint":
                raise ValueError(f"{address} is not a token mint on Solana")
            decimals = parsed["info"]["decimals"]
    else:
        if decimals is None:
            raw = rpc_with_fallback(rpcs, "eth_call", [{"to": address, "data": "0x313ce567"}, "latest"])
            if not raw or raw == "0x":
                raise ValueError(f"{address} is not an ERC-20 token on {chain}")
            decimals = int(raw, 16)
        if not symbol:
            try:
                symbol = evm_string(rpc_with_fallback(rpcs, "eth_call", [{"to": address, "data": "0x95d89b41"}, "latest"]))
            except Exception:
                pass
    return symbol, int(decimals), meta.get("price")


def parse_asset_target(what, chain, config):
    """-> (kind, chain, address|None)."""
    low = what.lower()
    if low in ("usdc", "native", "gas"):
        if chain not in (None, "*") and chain not in CHAINS:
            sys.exit(f"Unknown chain {chain}; choose from: *, {', '.join(CHAINS)}")
        return ("usdc" if low == "usdc" else "native"), (chain or "*"), None
    if EVM_RE.match(what):
        evm_with_wallets = [c for c in wallet_chains(config) if c in EVM_CHAINS]
        if chain is None:
            if len(evm_with_wallets) != 1:
                sys.exit("Which EVM chain is this token on? Pass --chain "
                         f"({', '.join(evm_with_wallets or EVM_CHAINS)}).")
            chain = evm_with_wallets[0]
        if chain not in EVM_CHAINS:
            sys.exit(f"{what} is an EVM contract; --chain must be one of: {', '.join(EVM_CHAINS)}")
        return "token", chain, what.lower()
    if chain == "near" or (chain is None and looks_like_near(what.lower())):
        if not NEAR_RE.match(what.lower()):
            sys.exit(f"Not a valid NEAR contract id: {what}")
        return "token", "near", what.lower()
    if SOLANA_RE.match(what):
        if chain not in (None, "solana"):
            sys.exit(f"{what} looks like a Solana mint, not a {chain} contract")
        return "token", "solana", what
    sys.exit(f"Expected usdc, native or a token contract address, got: {what}")  # noqa


def entry_matches(e, kind, chain, address):
    if e.get("kind") != kind or e.get("chain") != chain:
        return False
    return kind != "token" or e.get("address", "").lower() == address.lower()


def cmd_asset_add(args):
    config = load_config()
    kind, chain, address = parse_asset_target(args.what.strip(), args.chain, config)
    if kind == "token" and address.lower() == CHAINS[chain]["usdc"].lower():
        kind, address = "usdc", None  # that contract is the built-in USDC
        if any(e.get("kind") == "usdc" and e.get("chain") == "*" for e in config.get("assets", DEFAULT_ASSETS)):
            print(f"Already tracked: that contract is USDC, which is counted on every chain.")
            return
    assets = config.setdefault("assets", [dict(a) for a in DEFAULT_ASSETS])
    if any(entry_matches(e, kind, chain, address) for e in assets):
        print("Already tracked.")
        return
    entry = {"chain": chain, "kind": kind}
    label = kind if chain == "*" else f"{kind} on {chain}"
    if kind == "token":
        try:
            symbol, decimals, price = token_metadata(config, chain, address)
        except Exception as err:
            sys.exit(f"Could not read token {address} on {chain}: {err}")
        if args.decimals is not None:
            decimals = args.decimals
        if symbol and symbol.islower():
            symbol = symbol.upper()
        symbol = args.symbol or symbol or address[:6]
        entry.update(address=address, symbol=symbol, decimals=decimals)
        if args.stable:
            entry["stable"] = True
        label = f"{symbol} on {chain} (decimals {decimals}, " + (
            f"price ${price:,.2f})" if price is not None and price >= 1 else
            f"price ${price:.4g})" if price is not None else "no price source: amount only)")
    if chain not in ("*",) and chain not in wallet_chains(config):
        print(f"Note: no {chain} wallet is tracked yet, so this shows up once you add one.")
    assets.append(entry)
    save_config(config)
    print(f"Tracking {label}")


def cmd_asset_remove(args):
    config = load_config()
    kind, chain, address = parse_asset_target(args.what.strip(), args.chain, config)
    assets = config.setdefault("assets", [dict(a) for a in DEFAULT_ASSETS])
    before = len(assets)
    if kind != "token" and chain == "*":
        # "*" removes the kind everywhere: the wildcard entry and any per-chain ones.
        config["assets"] = [e for e in assets if e.get("kind") != kind]
    else:
        config["assets"] = [e for e in assets if not entry_matches(e, kind, chain, address)]
        if kind != "token" and len(config["assets"]) == before and chain in wallet_chains(config) and any(
            e.get("kind") == kind and e.get("chain") == "*" for e in assets
        ):
            # Narrow a wildcard: keep the kind on every other chain that has wallets.
            config["assets"] = [e for e in assets if not (e.get("kind") == kind and e.get("chain") == "*")]
            config["assets"] += [{"chain": c, "kind": kind} for c in wallet_chains(config) if c != chain]
    if config["assets"] == assets:
        sys.exit("That asset is not tracked.")
    save_config(config)
    print(f"Stopped tracking {args.what}" + (f" on {chain}" if chain != "*" else ""))


def cmd_display(args):
    config = load_config()
    config["display"] = args.mode
    save_config(config)
    print(f"Breakdown: {args.mode}")


def cmd_status(args):
    config = load_config()
    resolved = resolve_assets(config)
    tracked = {(a["chain"], a["id"]) for a in resolved}
    chains = wallet_chains(config)
    options = []
    for c in chains:
        n = CHAINS[c]["native"]
        options.append({"chain": c, "kind": "native", "symbol": n["symbol"], "tracked": (c, "native") in tracked,
                        "command": f"asset add native --chain {c}"})
        options.append({"chain": c, "kind": "usdc", "symbol": "USDC", "tracked": (c, "usdc") in tracked,
                        "command": f"asset add usdc --chain {c}"})
    status = {
        "label": config.get("label", "WALLET"),
        "display": config.get("display", "auto"),
        "wallets": config.get("wallets", []),
        "chains_with_wallets": chains,
        "tracked": [{k: a.get(k) for k in ("chain", "symbol", "kind", "address")} for a in resolved],
        "untracked_options": [o for o in options if not o["tracked"]],
        "supported_chains": list(CHAINS),
        "installed": (load_settings().get("statusLine") or {}).get("command") == our_command(),
    }
    if args.json:
        print(json.dumps(status, indent=2))
        return
    print(f"installed: {status['installed']}   display: {status['display']}")
    print("wallets:", ", ".join(f"{w['chain']} {w['address']}" for w in status["wallets"]) or "none")
    print("tracking:", ", ".join(f"{t['symbol']}@{t['chain']}" for t in status["tracked"]) or "nothing")
    print("can add:", ", ".join(f"{o['symbol']}@{o['chain']}" for o in status["untracked_options"]) or "-")


# ---------------------------------------------------------------- settings

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
    p.add_argument("--chain", choices=list(CHAINS), help="EVM chain (default: base); Solana and NEAR (x.near, 64-hex) are auto-detected")
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

    asset = sub.add_parser("asset", help="choose which assets are counted").add_subparsers(dest="asset_cmd", required=True)
    for name, func, help_ in (("add", cmd_asset_add, "track an asset"), ("remove", cmd_asset_remove, "stop tracking it")):
        p = asset.add_parser(name, help=help_)
        p.add_argument("what", help="usdc, native (gas token: SOL/ETH/POL) or a token contract/mint address")
        p.add_argument("--chain", help="chain, or * for every chain with a wallet (default for usdc/native)")
        if name == "add":
            p.add_argument("--symbol", help="override the detected symbol")
            p.add_argument("--decimals", type=int, help="override the detected decimals")
            p.add_argument("--stable", action="store_true", help="value it at $1 (USD stablecoin)")
        p.set_defaults(func=func)

    p = sub.add_parser("display", help="breakdown after the total")
    p.add_argument("mode", choices=["auto", "asset", "chain", "none"])
    p.set_defaults(func=cmd_display)

    p = sub.add_parser("status", help="wallets, tracked assets and what else can be added")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

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
