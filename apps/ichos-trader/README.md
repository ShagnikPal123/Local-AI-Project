# Ichos Trader

The trading tab of Nyx Ichos, split off into its own app. It scans hundreds of markets (crypto,
stocks, ETFs and currencies), ranks them on liquidity, spread, depth and order flow, and a small
team of bots trades the best of them **with practice money only**. It runs 24/7 and switches itself
off when it is slow or losing.

This folder imports nothing from Nyx, so it can move to its own repository unchanged.

## Start it

```bash
cd apps/ichos-trader
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt     # Windows (bin/python elsewhere)
.venv/Scripts/python.exe run_trader.py                          # then open http://127.0.0.1:8100
```

`run_trader.py --forever` restarts it if it ever exits. `--offline` uses the built-in simulated
market (no internet needed; the dashboard says so). The first run builds the dashboard if Node.js
is installed (`cd web && npm install && npm run build` does the same by hand).

## What it does

| Part | What it does |
|---|---|
| **Dashboard** | Money and its predicted change, win rate, the ranked markets, biggest increases, what every bot is thinking, who is working, the next plan, predictions (graded after a day) and research |
| **Scanner** | About 200 markets a cycle in parallel (up to 1,000 as the list grows); keyless Coinbase and Yahoo prices, or the simulated market |
| **The team** | Scout, strategist (learns before the first buy), advisor, three traders (one rotates between the strongest coins), a mild skeptic that stops or shrinks fishy buys, a manager that moves money to what works and hires or retires traders, and a researcher |
| **Tuning** | Fully automatic by default. Any dial you move is pinned until you hand it back to auto |
| **Auto shut-down** | Stops after slow cycles in a row, a drawdown, or a day below where it started; pauses while prices are stale |
| **Speed** | Every cycle is timed per step and graded against what fast means for an internet trader ([DESIGN](docs/DESIGN.md)) |
| **Connectors** | Alpaca (practice account) recommended; Claude only when you press Ask ([CONNECTORS](docs/CONNECTORS.md)) |

## Safety

- **Practice money only.** Real money is refused in code (`risk.py`, `connectors/alpaca.py`).
- **Deny by default.** Every API route needs a signed-in person; changes need the owner. With no
  login set up it answers only to the PC it runs on. Others can sign in with Google or GitHub to
  see the setup, but never use its keys or its account.
- **Keys** live in environment variables or `data/secrets.json` (gitignored) and only ever come back
  as their last 4 characters.

## Developers

```bash
python -m pytest            # from apps/ichos-trader; no network, no keys
python tools/leak_sweep.py  # run before every commit (staged changes) or with a base: origin/main
```

[docs/API.md](docs/API.md) is the contract between the server and the dashboard.
