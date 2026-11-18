#!/usr/bin/env python3
"""Claude Code statusLine renderer: live balances of public wallet addresses.

Read-only and keyless. It reads wallets and tracked assets from
~/.wallet-statusline/config.json (managed by setup.py), queries public RPCs
for balances and the DeFiLlama coins API for prices, and keeps a short
on-disk cache so the frequent statusLine calls neither hammer the endpoints
nor slow down the UI. Standard library only.

Tracked assets (config "assets"; default is USDC on every chain):
  {"chain": "*" | <chain>, "kind": "usdc"}
  {"chain": "*" | <chain>, "kind": "native"}                  # SOL / ETH / POL
  {"chain": <chain>, "kind": "token", "address": <CA>, "symbol": "...", "decimals": N}
"*" applies the entry to every chain that has a tracked wallet.
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
DEFAULT_MAX_ITEMS = 4
TIMEOUT = 2.5
PRICE_API = "https://coins.llama.fi/prices/current/"
DEFAULT_ASSETS = [{"chain": "*", "kind": "usdc"}]

# chain id -> how to read balances on it. "short" is the label in the chain breakdown,
# "llama" the chain prefix DeFiLlama uses for token prices.
CHAINS = {
    "solana": {
        "kind": "solana",
        "short": "sol",
        "llama": "solana",
        "usdc": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "native": {"symbol": "SOL", "decimals": 9, "price": "coingecko:solana"},
        "rpcs": ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"],
    },
    "base": {
        "kind": "evm",
        "short": "base",
        "llama": "base",
        "usdc": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "native": {"symbol": "ETH", "decimals": 18, "price": "coingecko:ethereum"},
        "rpcs": ["https://base-rpc.publicnode.com", "https://mainnet.base.org"],
    },
    "ethereum": {
        "kind": "evm",
        "short": "eth",
        "llama": "ethereum",
        "usdc": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "native": {"symbol": "ETH", "decimals": 18, "price": "coingecko:ethereum"},
        "rpcs": ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"],
    },
    "arbitrum": {
        "kind": "evm",
        "short": "arb",
        "llama": "arbitrum",
        "usdc": "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
        "native": {"symbol": "ETH", "decimals": 18, "price": "coingecko:ethereum"},
        "rpcs": ["https://arbitrum-one-rpc.publicnode.com", "https://arb1.arbitrum.io/rpc"],
    },
    "optimism": {
        "kind": "evm",
        "short": "op",
        "llama": "optimism",
        "usdc": "0x0b2c639c533813f4aa9d7837caf62653d097ff85",
        "native": {"symbol": "ETH", "decimals": 18, "price": "coingecko:ethereum"},
        "rpcs": ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io"],
    },
    "polygon": {
        "kind": "evm",
        "short": "pol",
        "llama": "polygon",
        "usdc": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
        "native": {"symbol": "POL", "decimals": 18, "price": "coingecko:polygon-ecosystem-token"},
        "rpcs": ["https://polygon-bor-rpc.publicnode.com", "https://polygon-rpc.com"],
    },
}

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
ACCENT = "\x1b[38;2;37;99;235m"
GRAY = "\x1b[38;2;110;110;110m"


# ---------------------------------------------------------------- transport

def http_json(url, payload=None):
    headers = {"User-Agent": "wallet-statusline"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read())


def rpc_call(url, method, params):
    body = http_json(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
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


def fetch_prices(keys):
    """DeFiLlama coins API -> {lowercased key: {"price", "symbol", "decimals"?}}."""
    if not keys:
        return {}
    coins = http_json(PRICE_API + ",".join(sorted(keys)))["coins"]
    return {k.lower(): v for k, v in coins.items()}


# ---------------------------------------------------------------- assets

def chain_rpcs(config, chain):
    return (config.get("rpc") or {}).get(chain) or CHAINS[chain]["rpcs"]


def asset_spec(chain, entry):
    """Resolve one config entry to a concrete asset on one chain."""
    c = CHAINS[chain]
    kind = entry.get("kind")
    if kind == "usdc":
        return {"id": "usdc", "chain": chain, "kind": "token", "address": c["usdc"],
                "symbol": "USDC", "decimals": 6, "stable": True, "price_key": None}
    if kind == "native":
        n = c["native"]
        return {"id": "native", "chain": chain, "kind": "native", "symbol": n["symbol"],
                "decimals": n["decimals"], "stable": False, "price_key": n["price"]}
    if kind == "token" and entry.get("address"):
        addr = entry["address"]
        return {"id": addr, "chain": chain, "kind": "token", "address": addr,
                "symbol": entry.get("symbol") or addr[:6], "decimals": int(entry.get("decimals", 0)),
                "stable": bool(entry.get("stable")), "price_key": f"{c['llama']}:{addr}"}
    return None


def wallet_chains(config):
    seen = []
    for w in config.get("wallets", []):
        if w.get("chain") in CHAINS and w["chain"] not in seen:
            seen.append(w["chain"])
    return seen


def resolve_assets(config):
    """Concrete (chain, asset) list for chains that have wallets, deduplicated."""
    entries = config.get("assets", DEFAULT_ASSETS)
    chains = wallet_chains(config)
    out = {}
    for e in entries:
        targets = chains if e.get("chain") == "*" else [e.get("chain")]
        for chain in targets:
            if chain not in chains:
                continue
            spec = asset_spec(chain, e)
            if spec and (chain, spec["id"]) not in out:
                out[(chain, spec["id"])] = spec
    return list(out.values())


# ---------------------------------------------------------------- balances

def fetch_balance(config, wallet, asset):
    rpcs = chain_rpcs(config, wallet["chain"])
    addr = wallet["address"]
    if CHAINS[wallet["chain"]]["kind"] == "solana":
        if asset["kind"] == "native":
            return rpc_with_fallback(rpcs, "getBalance", [addr])["value"] / 10 ** asset["decimals"]
        accounts = rpc_with_fallback(
            rpcs, "getTokenAccountsByOwner",
            [addr, {"mint": asset["address"]}, {"encoding": "jsonParsed"}],
        )["value"]
        return sum(
            float(a["account"]["data"]["parsed"]["info"]["tokenAmount"].get("uiAmountString") or 0)
            for a in accounts
        )
    if asset["kind"] == "native":
        raw = rpc_with_fallback(rpcs, "eth_getBalance", [addr, "latest"])
    else:
        data = "0x70a08231" + addr.lower().removeprefix("0x").rjust(64, "0")  # balanceOf(address)
        raw = rpc_with_fallback(rpcs, "eth_call", [{"to": asset["address"], "data": data}, "latest"])
    return int(raw, 16) / 10 ** asset["decimals"] if raw and raw != "0x" else 0.0


def wallet_key(wallet):
    return f"{wallet['chain']}:{wallet['address']}"


def balance_key(wallet, asset):
    return f"{wallet_key(wallet)}|{asset['id']}"


def pairs(config, assets):
    return [(w, a) for w in config.get("wallets", []) for a in assets if a["chain"] == w.get("chain")]


def refresh(config, assets, cache):
    """Fetch balances and prices in parallel; reuse cached values for anything that fails."""
    cache = cache or {}
    old_bal, old_px = cache.get("balances", {}), cache.get("prices", {})
    todo = pairs(config, assets)
    price_keys = {a["price_key"] for a in assets if a["price_key"]}
    balances, prices, stale = {}, dict(old_px), False

    with ThreadPoolExecutor(max_workers=max(2, min(10, len(todo) + 1))) as pool:
        price_future = pool.submit(fetch_prices, price_keys)
        futures = {balance_key(w, a): pool.submit(fetch_balance, config, w, a) for w, a in todo}
        for key, fut in futures.items():
            try:
                balances[key] = fut.result()
            except Exception:
                if key in old_bal:
                    balances[key] = old_bal[key]
                stale = True
        try:
            for k, v in price_future.result().items():
                if v.get("price") is not None:
                    prices[k] = v["price"]
        except Exception:
            stale = stale or any(k.lower() not in prices for k in price_keys)

    return {"balances": balances, "prices": prices, "fetched_at": time.time(), "partial": stale}


# ---------------------------------------------------------------- rendering

def fmt_amount(x):
    if x >= 1_000_000:
        return f"{x / 1_000_000:.2f}M"
    if x >= 10_000:
        return f"{x / 1_000:.1f}K"
    if x >= 1:
        return f"{x:,.2f}".rstrip("0").rstrip(".")
    if x == 0:
        return "0"
    return f"{x:.4g}"


def usd_value(asset, amount, prices):
    if asset["stable"]:
        return amount
    price = prices.get(asset["price_key"].lower()) if asset["price_key"] else None
    return amount * price if price is not None else None


def format_line(config, assets, balances, prices, stale):
    rows = []  # (wallet, asset, amount or None, usd or None)
    for w, a in pairs(config, assets):
        amt = balances.get(balance_key(w, a))
        rows.append((w, a, amt, usd_value(a, amt, prices) if amt is not None else None))

    total = sum(r[3] for r in rows if r[3] is not None)
    label = config.get("label") or "WALLET"
    marker = f"{DIM}~ {RESET}" if stale else ""
    head = f"{BOLD}{ACCENT}{label}{RESET} {BOLD}{ACCENT}${total:,.2f}{RESET}"

    mode = config.get("display", "auto")
    if mode == "auto":
        mode = "chain" if all(a["stable"] for a in assets) else "asset"
    items = chain_items(rows) if mode == "chain" else asset_items(rows) if mode == "asset" else []

    max_items = int(config.get("max_items", DEFAULT_MAX_ITEMS))
    if len(items) <= 1 and mode == "chain":
        items = []
    extra = len(items) - max_items
    if extra > 0:
        items = items[:max_items] + [f"+{extra}"]
    if not items:
        return marker + head
    parts = f"{DIM} · {RESET}".join(f"{GRAY}{i}{RESET}" for i in items)
    return f"{marker}{head} {DIM}({RESET}{parts}{DIM}){RESET}"


def chain_items(rows):
    per_chain, missing = {}, set()
    for w, _a, amt, usd in rows:
        per_chain.setdefault(w["chain"], 0.0)
        if amt is None:
            missing.add(w["chain"])
        elif usd is not None:
            per_chain[w["chain"]] += usd
    return [
        f"{CHAINS[c]['short']} {'?' if c in missing else f'${v:,.2f}'}" for c, v in per_chain.items()
    ]


def asset_items(rows):
    groups = {}  # symbol -> [amount, usd, priced?, missing?, stable?]
    for _w, a, amt, usd in rows:
        g = groups.setdefault(a["symbol"], [0.0, 0.0, True, False, a["stable"]])
        if amt is None:
            g[3] = True
            continue
        g[0] += amt
        if usd is None:
            g[2] = False
        else:
            g[1] += usd
    ordered = sorted(groups.items(), key=lambda kv: (not kv[1][2], -kv[1][1]))
    items = []
    for sym, (amt, usd, priced, missing, stable) in ordered:
        if missing and amt == 0:
            items.append(f"{sym} ?")
        elif amt == 0:
            continue
        elif stable:
            items.append(f"{sym} ${usd:,.2f}")
        elif priced:
            items.append(f"{fmt_amount(amt)} {sym} ${usd:,.2f}")
        else:
            items.append(f"{fmt_amount(amt)} {sym}")
    return items


# ---------------------------------------------------------------- entry

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


def config_fingerprint(config, assets):
    keys = sorted(balance_key(w, a) for w, a in pairs(config, assets))
    return hashlib.sha256(json.dumps(keys).encode()).hexdigest()[:16]


def main():
    config = load_json(CONFIG_FILE)
    if not config or not config.get("wallets"):
        print(f"{DIM}wallet: no addresses configured{RESET}")
        return

    assets = resolve_assets(config)
    fingerprint = config_fingerprint(config, assets)
    cache = load_json(CACHE_FILE)
    fresh_enough = cache and time.time() - cache.get("fetched_at", 0) < config.get("ttl_seconds", DEFAULT_TTL)

    if cache and cache.get("fingerprint") == fingerprint and fresh_enough:
        print(format_line(config, assets, cache["balances"], cache.get("prices", {}), cache.get("partial", False)))
        return

    # Old balances are reused per wallet+asset, so adding an asset doesn't blank the others.
    fresh = refresh(config, assets, cache)
    if not fresh["balances"]:
        print(f"{DIM}wallet: unavailable{RESET}")
        return
    fresh["fingerprint"] = fingerprint
    try:
        save_cache(fresh)
    except OSError:
        pass
    print(format_line(config, assets, fresh["balances"], fresh["prices"], fresh["partial"]))


if __name__ == "__main__":
    main()
