# claude-wallet-statusline

A [Claude Code](https://docs.claude.com/en/docs/claude-code) skill that shows the live USDC balance of any public wallet address in the status line:

```
WALLET $1,240.50 (base $1,000.00 · sol $240.50)
```

- **Watch-only**: you give it public addresses. No keys, seed phrases or wallet connection.
- **Keyless**: balances come straight from public RPCs. No accounts or API keys.
- **Fast**: a 30 s on-disk cache, parallel requests, a 2.5 s timeout and a fallback RPC per chain.
- **No dependencies**: Python 3.9+ standard library only.

Supported chains (USDC): Solana, Base, Ethereum, Arbitrum, Optimism, Polygon.

## Install

```sh
git clone https://github.com/lopushok9/claude-wallet-statusline ~/.claude/skills/wallet-statusline
```

Then ask Claude Code something like:

> show my wallet 0xAbC… and Hu7x… in the status line

Claude adds the addresses and registers the status line. Restart Claude Code to see it.

### Without Claude

```sh
cd ~/.claude/skills/wallet-statusline
python3 scripts/setup.py add 0xYourBaseAddress            # EVM defaults to Base
python3 scripts/setup.py add 0xYourAddress --chain arbitrum
python3 scripts/setup.py add YourSolanaAddress            # auto-detected
python3 scripts/setup.py install
python3 scripts/setup.py render                           # preview once
```

## Commands

| Command | What it does |
|---|---|
| `add <address> [--chain C] [--name N]` | Track an address |
| `remove <address> [--chain C]` | Stop tracking it |
| `list` | Show tracked wallets and RPC overrides |
| `label <text>` | Change the `WALLET` label |
| `rpc <chain> <url>…` | Use your own RPC endpoints (no urls = defaults) |
| `install [--force]` | Add the `statusLine` to `~/.claude/settings.json` |
| `uninstall` | Remove it and restore any status line it replaced |
| `render` | Print the line once |

`install` will not overwrite a different status line unless you pass `--force`. The old one is saved and `uninstall` restores it.

## How it works

`install` copies `scripts/statusline.py` to `~/.wallet-statusline/` and points Claude Code's `statusLine` at it, refreshing every 30 seconds. On each run the script:

1. reads `~/.wallet-statusline/config.json`;
2. returns the cached result if it is under 30 s old;
3. otherwise queries every wallet in parallel:
   - Solana: `getTokenAccountsByOwner` for the USDC mint;
   - EVM: `eth_call` → `balanceOf(address)` on the chain's native USDC contract;
4. if an RPC fails it tries the next one, then falls back to the cached value and puts `~` in front of the line.

Set `WALLET_STATUSLINE_HOME` to keep the config somewhere other than `~/.wallet-statusline`.

## Privacy

Your addresses are sent to the public RPC providers (PublicNode, Solana Foundation, chain foundations, dRPC), and they can see your IP. To avoid that, point each chain at your own node with `setup.py rpc`.

## License

MIT
