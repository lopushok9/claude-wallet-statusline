# claude-wallet-statusline

A [Claude Code](https://docs.claude.com/en/docs/claude-code) skill that shows live balances of any public wallet address in the status line:

```
WALLET $1,240.50 (1.25 SOL $210.40 · USDC $1,000.00 · 0.012 ETH $30.10)
```

USDC is tracked by default. Gas tokens (SOL, ETH, POL) and any token by contract address are opt-in: ask Claude ("also track SOL", "add token 0x…") or pick from the menu it shows.

- **Watch-only**: you give it public addresses. No keys, seed phrases or wallet connection.
- **Keyless**: balances come straight from public RPCs and prices from the free DeFiLlama API. No accounts or API keys.
- **Fast**: a 30 s on-disk cache, parallel requests, a 2.5 s timeout and a fallback RPC per chain.
- **No dependencies**: Python 3.9+ standard library only.

Supported chains: Solana, Base, Ethereum, Arbitrum, Optimism, Polygon.

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
python3 scripts/setup.py asset add native                 # gas tokens on every wallet chain
python3 scripts/setup.py asset add <token contract> --chain base
python3 scripts/setup.py install
python3 scripts/setup.py render                           # preview once
```

## Commands

| Command | What it does |
|---|---|
| `add <address> [--chain C] [--name N]` | Track an address |
| `remove <address> [--chain C]` | Stop tracking it |
| `list` / `status [--json]` | Show wallets, tracked assets and what else can be added |
| `asset add usdc\|native\|<CA> [--chain C\|*]` | Track USDC, the gas token, or a token by contract/mint address (symbol and decimals are detected) |
| `asset remove usdc\|native\|<CA> [--chain C\|*]` | Stop tracking it |
| `display auto\|asset\|chain\|none` | Breakdown after the total |
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
3. otherwise fetches, all in parallel:
   - Solana: `getBalance` (SOL) and `getTokenAccountsByOwner` per mint (SPL and Token-2022);
   - EVM: `eth_getBalance` (gas token) and `eth_call` → `balanceOf(address)` per token;
   - prices: one request to `coins.llama.fi/prices/current/…` for all non-stable assets;
4. if an RPC fails it tries the next one, then falls back to the cached value and puts `~` in front of the line. A token with no price is shown as an amount and left out of the USD total.

Set `WALLET_STATUSLINE_HOME` to keep the config somewhere other than `~/.wallet-statusline`.

## Privacy

Your addresses are sent to the public RPC providers (PublicNode, Solana Foundation, chain foundations, dRPC), and the token ids to DeFiLlama. Both can see your IP. To avoid that, point each chain at your own node with `setup.py rpc`.

## License

MIT
