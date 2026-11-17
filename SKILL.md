---
name: wallet-statusline
description: Show live USDC balances of public wallet addresses (Solana, Base, Ethereum, Arbitrum, Optimism, Polygon) in the Claude Code status line. Use when the user wants a wallet balance in the status line, or wants to add, remove, list or relabel the wallets it tracks, change its RPC endpoints, or turn it off.
---

# Wallet status line

Adds a line under the Claude Code input box like:

```
WALLET $1,240.50 (base $1,000.00 · sol $240.50)
```

It only reads **public addresses** and queries **public RPCs**. No private
keys, seed phrases or API keys are involved: never ask the user for any.
The value is USDC only (native SOL/ETH and other tokens are not counted).

All commands use `scripts/setup.py` in this skill's directory (the base
directory shown when the skill loads). Run them with `python3`.

## Enable

1. Get the address(es) from the user if they didn't give them. EVM addresses
   (`0x…`) default to Base; ask which chain only if they mention another one.
   Solana addresses are detected automatically.
2. Add each one:
   ```
   python3 <skill-dir>/scripts/setup.py add <address> [--chain base|ethereum|arbitrum|optimism|polygon]
   ```
3. Register the status line:
   ```
   python3 <skill-dir>/scripts/setup.py install
   ```
   If it reports that a different statusLine already exists, tell the user
   and ask before re-running with `--force` (their old one is saved and
   restored by `uninstall`).
4. Run `python3 <skill-dir>/scripts/setup.py render` to show the line once,
   then tell the user it appears after restarting Claude Code (or in a new
   session) and refreshes about every 30 seconds.

## Manage

| Request | Command |
|---|---|
| Show tracked wallets | `setup.py list` |
| Stop tracking one | `setup.py remove <address>` |
| Change the label | `setup.py label "<text>"` |
| Use own RPC (e.g. a keyed provider) | `setup.py rpc <chain> <url> [<url>…]` (no urls = defaults) |
| Turn it off | `setup.py uninstall` |

Wallet changes take effect on the next refresh; no restart needed.

## Display

- `~` before the label: at least one RPC failed and the cached value is shown.
- `wallet: no addresses configured`: run `add`.
- `wallet: unavailable`: every RPC failed and there is no cache yet.

Note for the user: the tracked addresses are sent to the public RPC
providers in each request, which links those addresses to their IP.
