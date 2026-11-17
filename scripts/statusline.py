#!/usr/bin/env python3
"""Claude Code statusLine renderer: live USDC balances of public wallet addresses.

Read-only and keyless. It reads the wallet list from
~/.wallet-statusline/config.json (managed by setup.py), queries public RPCs
directly and keeps a short on-disk cache, so the frequent statusLine calls
neither hammer the RPCs nor slow down the UI. Standard library only.
"""
import hashlib
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HOME_DIR = os.environ.get("WALLET_STATUSLINE_HOME") or os.path.expanduser("~/.wallet-statusline")
CONFIG_FILE = os.path.join(HOME_DIR, "config.json")
CACHE_FILE = os.path.join(HOME_DIR, "cache.json")

DEFAULT_TTL = 30
TIMEOUT = 2.5

# chain id -> how to read USDC on it. "short" is the label in the breakdown.
CHAINS = {
    "solana": {
        "kind": "solana",
        "short": "sol",
        "usdc": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "rpcs": ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"],
    },
    "base": {
        "kind": "evm",
        "short": "base",
        "usdc": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "rpcs": ["https://base-rpc.publicnode.com", "https://mainnet.base.org"],
    },
    "ethereum": {
        "kind": "evm",
        "short": "eth",
        "usdc": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "rpcs": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"],
    },
    "arbitrum": {
        "kind": "evm",
        "short": "arb",
        "usdc": "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
        "rpcs": ["https://arbitrum-one-rpc.publicnode.com", "https://arb1.arbitrum.io/rpc"],
    },
    "optimism": {
        "kind": "evm",
        "short": "op",
        "usdc": "0x0b2c639c533813f4aa9d7837caf62653d097ff85",
        "rpcs": ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io"],
    },
    "polygon": {
        "kind": "evm",
        "short": "pol",
        "usdc": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
        "rpcs": ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"],
    },
}

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
ACCENT = "\x1b[38;2;56;189;248m"
GRAY = "\x1b[38;2;156;163;175m"


def rpc_call(url, method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "wallet-statusline"}
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"{url}: {body['error']}")
    return body["result"]


def rpc_with_fallback(rpcs, method, params):
    last_err = None
    for url in rpcs:
        try:
            return rpc_call(url, method, params)
        except Exception as err:  # try the next endpoint
            last_err = err
    raise last_err or RuntimeError("no RPC endpoints configured")


def fetch_solana_usdc(chain, rpcs, address):
    accounts = rpc_with_fallback(
        rpcs,
        "getTokenAccountsByOwner",
        [address, {"mint": chain["usdc"]}, {"encoding": "jsonParsed"}],
    )["value"]
    total = 0.0
    for acc in accounts:
        amount = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]
        total += float(amount.get("uiAmountString") or 0)
    return total


def fetch_evm_usdc(chain, rpcs, address):
    data = "0x70a08231" + address.lower().removeprefix("0x").rjust(64, "0")  # balanceOf(address)
    raw = rpc_with_fallback(rpcs, "eth_call", [{"to": chain["usdc"], "data": data}, "latest"])
    return int(raw, 16) / 1_000_000 if raw and raw != "0x" else 0.0


def wallet_key(wallet):
    return f"{wallet['chain']}:{wallet['address']}"


def fetch_one(wallet, rpc_overrides):
    chain = CHAINS[wallet["chain"]]
    rpcs = rpc_overrides.get(wallet["chain"]) or chain["rpcs"]
    if chain["kind"] == "solana":
        return fetch_solana_usdc(chain, rpcs, wallet["address"])
    return fetch_evm_usdc(chain, rpcs, wallet["address"])


def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_cache(data):
    os.makedirs(HOME_DIR, exist_ok=True)
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, CACHE_FILE)


def config_fingerprint(config):
    wallets = sorted(wallet_key(w) for w in config.get("wallets", []))
    return hashlib.sha256(json.dumps(wallets).encode()).hexdigest()[:16]


def refresh(config, cache):
    """Fetch every wallet in parallel; reuse cached values for any that fail."""
    wallets = [w for w in config.get("wallets", []) if w.get("chain") in CHAINS]
    old = (cache or {}).get("balances", {})
    balances, stale = {}, False
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(wallets)))) as pool:
        futures = {wallet_key(w): pool.submit(fetch_one, w, config.get("rpc", {})) for w in wallets}
        for key, fut in futures.items():
            try:
                balances[key] = fut.result()
            except Exception:
                if key in old:
                    balances[key] = old[key]
                stale = True
    return {"balances": balances, "fetched_at": time.time(), "partial": stale}


def format_line(config, balances, stale):
    per_chain, missing = {}, set()
    for w in config.get("wallets", []):
        if w.get("chain") not in CHAINS:
            continue
        per_chain.setdefault(w["chain"], 0.0)
        key = wallet_key(w)
        if key in balances:
            per_chain[w["chain"]] += balances[key]
        else:
            missing.add(w["chain"])
    total = sum(per_chain.values())
    label = config.get("label") or "WALLET"
    marker = f"{DIM}~ {RESET}" if stale else ""
    head = f"{BOLD}{ACCENT}{label}{RESET} {BOLD}{ACCENT}${total:,.2f}{RESET}"
    if len(per_chain) <= 1:
        return marker + head
    parts = f"{DIM} · {RESET}".join(
        f"{GRAY}{CHAINS[c]['short']} {'?' if c in missing else f'${v:,.2f}'}{RESET}"
        for c, v in per_chain.items()
    )
    return f"{marker}{head} {DIM}({RESET}{parts}{DIM}){RESET}"


def main():
    config = load_json(CONFIG_FILE)
    if not config or not config.get("wallets"):
        print(f"{DIM}wallet: no addresses configured{RESET}")
        return

    fingerprint = config_fingerprint(config)
    cache = load_json(CACHE_FILE)
    if cache and cache.get("fingerprint") != fingerprint:
        cache = None  # wallet list changed; old numbers no longer apply
    ttl = config.get("ttl_seconds", DEFAULT_TTL)

    if cache and time.time() - cache.get("fetched_at", 0) < ttl:
        print(format_line(config, cache["balances"], cache.get("partial", False)))
        return

    fresh = refresh(config, cache)
    if not fresh["balances"]:
        print(f"{DIM}wallet: unavailable{RESET}")
        return
    fresh["fingerprint"] = fingerprint
    try:
        save_cache(fresh)
    except OSError:
        pass
    print(format_line(config, fresh["balances"], fresh["partial"]))


if __name__ == "__main__":
    main()
