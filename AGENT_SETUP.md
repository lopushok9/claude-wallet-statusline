# Agent setup guide: wallet status line

You are setting up a Claude Code status line that shows the live balance of
the user's **public** wallet addresses. Follow these steps in order. Run all
commands yourself; ask the user only for what is marked **Ask**.

Rules:
- Only public addresses are needed. Never ask for, accept or store a private
  key, seed phrase or API key. If the user pastes one, tell them to rotate it
  and do not use it.
- Do not edit `~/.claude/settings.json` by hand: `setup.py install` does it
  safely.
- Requires Python 3.9+ (`python3 --version`) and git.

## 1. Install the skill

```sh
SKILL_DIR="$HOME/.claude/skills/wallet-statusline"
if [ -d "$SKILL_DIR/.git" ]; then
  git -C "$SKILL_DIR" pull --ff-only
else
  git clone https://github.com/lopushok9/claude-wallet-statusline "$SKILL_DIR"
fi
```

Every command below is `python3 "$SKILL_DIR/scripts/setup.py" …`.

Run `setup.py status` first. If wallets are already configured, show them to
the user and ask whether to keep, add to or replace them.

## 2. Add wallets

**Ask** for the wallet address(es) unless the user already gave them. For each
EVM address (`0x…`) also ask which chain it is on if they didn't say: Base,
Ethereum, Arbitrum, Optimism or Polygon. If they don't care, use Base. Solana
addresses are detected automatically.

```sh
setup.py add <address>                      # Solana, or EVM on Base
setup.py add <address> --chain arbitrum     # EVM on another chain
setup.py add <address> --name "Trading"     # optional name
```

The same EVM address on several chains needs one `add` per chain. If a command
exits with an error, show the user its message and fix the input (wrong chain,
typo in the address) before going on.

## 3. Choose what to count

USDC is counted on every wallet chain by default. Gas tokens (SOL, ETH, POL)
and other tokens are opt-in.

If the user already said what to track, add it directly:

```sh
setup.py asset add native --chain solana    # SOL
setup.py asset add native --chain base      # ETH on Base
setup.py asset add native                   # gas token on every wallet chain
setup.py asset add <contract or mint>       # any token; add --chain <evm chain> if asked
setup.py asset remove usdc                  # stop counting USDC
```

Otherwise **Ask** with a multiple-choice menu. In Claude Code, use the
`AskUserQuestion` tool with `multiSelect: true`:

1. Run `setup.py status --json`. Build the options from `untracked_options`.
   Use at most 4 options and merge similar ones, e.g. "ETH on all EVM chains".
2. Say in the question that a token can be added by pasting its contract
   address in "Other".
3. Run `asset add` for each selected option and for any address they typed.

For each token added by address, tell the user the symbol, decimals and price
that `asset add` printed so they can confirm it found the right token. If it
printed "no price source", the token is shown as an amount only and is left
out of the USD total.

## 4. Turn it on

```sh
setup.py install
```

If it says a different statusLine already exists, show it to the user and
**Ask** whether to replace it. Only on a yes, run `setup.py install --force`.
The old one is saved, and `setup.py uninstall` restores it.

## 5. Show the result

```sh
setup.py render
```

Show the user the printed line. Example:

```
WALLET $1,240.50 (1.25 SOL $210.40 · USDC $1,000.00 · 0.012 ETH $30.10)
```

Then tell them:
- The line appears under the input box after restarting Claude Code (or in a
  new session) and refreshes about every 30 seconds.
- `~` before the label means some request failed and cached numbers are shown.
- They can change it any time by asking you, e.g. "add BONK", "stop tracking
  ETH", "change the label to TREASURY", "show the breakdown by chain", "turn
  the wallet status line off".
- The addresses are sent to public RPC providers, and token ids to DeFiLlama,
  for each refresh. `setup.py rpc <chain> <url>` switches a chain to their own
  RPC endpoint.

## Command reference

| Command | Purpose |
|---|---|
| `status [--json]` | Wallets, tracked assets, options not tracked yet, install state |
| `add <address> [--chain C] [--name N]` / `remove <address> [--chain C]` | Wallets |
| `asset add\|remove usdc\|native\|<CA> [--chain C\|*]` | What is counted |
| `asset add <CA> [--symbol S] [--decimals N] [--stable]` | Override detected token data; `--stable` values it at $1 |
| `display auto\|asset\|chain\|none` | Breakdown after the total |
| `label <text>` | Text before the total (default `WALLET`) |
| `rpc <chain> <url>…` | Custom RPC endpoints; no urls resets them |
| `install [--force]` / `uninstall` | Turn the status line on / off |
| `render` | Print the line once |

Supported chains: `solana`, `base`, `ethereum`, `arbitrum`, `optimism`, `polygon`.
