---
name: wallet-statusline
description: Show live balances of public wallet addresses (Solana, NEAR, Base, Ethereum, Arbitrum, Optimism, Polygon) in the Claude Code status line. USDC by default; optionally gas tokens (SOL, ETH, POL, NEAR) and any token by contract address. Use when the user wants a wallet balance in the status line, or wants to add/remove wallets or tokens, change what the line shows, change RPCs, or turn it off.
---

# Wallet status line

Adds a line under the Claude Code input box like:

```
WALLET $1,240.50 (1.25 SOL $210.40 · USDC $1,000.00 · 0.012 ETH $30.10)
```

It only reads **public addresses**, queries **public RPCs** for balances and
the keyless DeFiLlama API for prices. No private keys, seed phrases or API
keys are involved: never ask the user for any.

All commands are `python3 <skill-dir>/scripts/setup.py …`, where
`<skill-dir>` is this skill's base directory (shown when the skill loads).

## Enable

1. Get the address(es) if the user didn't give them. EVM addresses (`0x…`)
   default to Base; pass `--chain` when the user names another chain.
   Solana addresses and NEAR accounts (`alice.near`, 64-hex implicit) are
   detected automatically; a top-level NEAR name without a dot (e.g. `aurora`)
   needs `--chain near`.
   ```
   setup.py add <address> [--chain base|ethereum|arbitrum|optimism|polygon|near] [--name <name>]
   ```
2. `setup.py install`. If it reports that a different statusLine already
   exists, tell the user and ask before re-running with `--force` (their old
   one is saved and restored by `uninstall`).
3. Offer the asset menu (below) once, so the user can add gas tokens. Skip it
   if they already said what to track.
4. `setup.py render` to show the line once. It appears in the UI after a
   restart of Claude Code (or in a new session) and refreshes about every 30 s.

## Choosing assets

USDC is tracked on every wallet chain by default. Gas tokens and other tokens
are opt-in.

**When the user names what they want, just do it, no menu:**

| User says | Command |
|---|---|
| "also track SOL" / "add ETH on Base" | `asset add native --chain solana` / `--chain base` |
| "track gas tokens" (all chains) | `asset add native` |
| "add token `<CA>`" | `asset add <CA>` (+ `--chain <evm chain>` if it asks; NEAR contracts like `usdt.tether-token.near` are detected) |
| "stop counting USDC on Solana" | `asset remove usdc --chain solana` |
| "remove `<CA>`" / "stop tracking ETH" | `asset remove <CA>` / `asset remove native --chain …` |

`ETH` refers to the gas token on base/ethereum/arbitrum/optimism, so if the user
says "ETH" and has wallets on several of those chains, add it to each one, or
ask which chains. For a CA, report the symbol, decimals and price that
`asset add` prints so the user can confirm it found the right token. If it
printed "no price source", the token is shown as an amount and left out of
the USD total. Add `--stable` only for a USD stablecoin that has no price.

**When the user is vague ("what can I track?", "set up tokens", or at
enable time), show an interactive menu:**

1. Run `setup.py status --json` and read `untracked_options` (gas tokens
   and USDC not tracked yet, per wallet chain) and `tracked`.
2. Call the `AskUserQuestion` tool with `multiSelect: true`. Use up to 4
   options built from `untracked_options`. Combine items when there are more,
   e.g. "ETH on all EVM chains", and put SOL first if there is a Solana wallet.
   Mention in the question that a token can be added by contract address
   through "Other".
3. Run `asset add` for each choice. If they typed a contract address in
   "Other", add it as a CA.
4. `setup.py render` to show the result.

## Other settings

| Request | Command |
|---|---|
| What is tracked | `setup.py status` |
| Remove a wallet | `setup.py remove <address>` |
| Change the label | `setup.py label "<text>"` |
| Breakdown after the total | `setup.py display auto\|asset\|chain\|none` (auto = by chain for USDC-only, by asset otherwise) |
| Own RPC (e.g. a keyed provider) | `setup.py rpc <chain> <url> [<url>…]` (no urls = defaults) |
| Turn it off | `setup.py uninstall` |

Changes apply on the next refresh; no restart needed. Any `setup.py` command
also syncs the installed renderer with this skill's version.

## Reading the line

- Zero balances are hidden in the per-asset breakdown; more than 4 items shows `+N`.
- `~` before the label: some RPC or price request failed and cached values are shown.
- `sol ?` / `SOL ?`: that balance couldn't be fetched and there is no cache yet.
- `wallet: no addresses configured`: run `add`.

Privacy note for the user: the tracked addresses go to the public RPC
providers and token ids to DeFiLlama with every refresh, which links the
addresses to their IP. Using their own RPC (`setup.py rpc`) avoids the RPC part.
