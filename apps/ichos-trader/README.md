# Ichos Trader

An AI trading bot that runs on your own computer. It scans hundreds of markets (crypto, stocks,
ETFs and currencies), ranks them on liquidity, spread, depth and order flow, and a small team of
bots trades the best of them. It learns before its first trade, keeps learning from how its own
trades went, runs 24/7, and switches itself off when it is slow or losing.

It has two modes, switched at the top of the dashboard:

- **Practice** (the default): training money in the built-in practice account, or a free Alpaca
  practice account that fills orders at real prices.
- **Real money**: your own Alpaca account, fully automatic, inside a budget you set, with a daily
  loss limit. Going live is a deliberate step (below).

This folder is a complete app on its own (it imports nothing from Nyx Ichos).

## Install on Windows (about 5 minutes, once)

1. **Install Python 3.11 or newer** from [python.org/downloads](https://www.python.org/downloads/).
   In the installer, tick **"Add python.exe to PATH"**. (Skip this if you already have it.)
2. **Download the trader.** On the GitHub page press **Code → Download ZIP**, then right-click the
   ZIP and choose **Extract All**. Put the folder somewhere permanent, such as `Documents`.
3. **Open the trader's folder** (`apps\ichos-trader` inside the extracted folder) and double-click
   **`Start Ichos Trader.bat`**.

The first run installs what it needs (a minute or two). After that it starts in a small window and
opens the dashboard at <http://127.0.0.1:8100>. Closing the small window stops the trader.

If Windows shows "Windows protected your PC", choose **More info → Run anyway**: the file is a
plain text script you can open in Notepad to read first. Nothing else needs installing; the
dashboard comes already built.

## Set it up (a couple of clicks)

The first time it opens you land on **Setup**:

1. **How much money may it use?** Type an amount or press 100 / 1,000 / 10,000 / 100,000, and pick a
   currency (16 to choose from; prices are converted into it).
2. **Which account?**
   - **Built-in practice**: nothing to sign up for.
   - **Alpaca practice**: sign up free at [alpaca.markets](https://alpaca.markets), open the
     **Paper** account, and paste its two API keys into Setup. The bots then trade that account,
     only ever with the amount you chose, and never touch anything else held in it.
3. Press **Save and start**.

## Switch to real money (when you are ready)

Run it on practice first and watch how it does. When you want it to trade real money:

1. Open an [Alpaca](https://alpaca.markets) live (brokerage) account and fund it. In Alpaca, create
   the **live** API keys (they are different from the Paper keys).
2. In the trader, press **Real money** in the top bar (or open **Setup → Mode → Real money**).
3. Set the **budget**: the most real money the bots may use. They only ever use the budget plus
   what they earn, never anything else in the account, and never borrow or short.
4. Set the **daily loss limit** (default 5% of the budget): past it, the trader stops for the day.
5. Paste the live keys and press **Connect live account** (this only reads the account; it never
   places an order).
6. Type **I understand this uses real money** and press **Use real money and start**.

The top bar then shows **Real money** in red. To go back, press **Practice** in the top bar: the
bots stop first, and anything they bought stays in your Alpaca account for you to keep or sell.
The usual shut-downs (a drawdown, slow cycles, a day below where it started) apply to real money
too. Trading carries risk: only use money you can afford to lose.

Everything else is optional:

| Page | What you can do |
|---|---|
| **Tuning** | It is fully automatic. Move any dial (risk, stop-loss, how many markets, pace) and that dial stays yours until you hand it back to auto. Also colours, light/dark, markets to scan, and the auto shut-down limits |
| **Connectors** | Brokers, price feeds, and Claude (only used when you press Ask; you add your own key) |
| **Setup** | Change the amount or the account any time |

Keys are saved in `data\secrets.json` on your computer and only ever shown as their last 4
characters.

## Keep it running 24/7

- **Start with Windows:** open a Command Prompt in the trader's folder and run
  `.venv\Scripts\python.exe run_trader.py --autostart on` (use `off` to undo). It then starts
  minimised every time you sign in, and restarts itself if it ever stops.
- Set your PC's sleep to **Never** while it trades (Settings → System → Power).

## Update to a new version

- **Downloaded as a ZIP:** download the new ZIP and extract it, then copy the old folder's
  **`data`** folder (your settings, practice account, keys and history) into the new
  `apps\ichos-trader` folder, and double-click `Start Ichos Trader.bat`. If the new version adds
  packages, delete the new folder's `.venv` first so the first run installs them.
- **Cloned with git:** stop the trader, run `git pull`, then
  `.venv\Scripts\python.exe -m pip install -r requirements.txt`, and start it again.

`data` is never in the download, so an update never overwrites your money or keys.

## Settings you can set before it starts (optional)

| Variable | What it does |
|---|---|
| `ICHOS_WORKERS` | How many prices it fetches at once (default: 4 per processor core, up to 64) |
| `ICHOS_TRADER_DATA` | Where it keeps its data (default: the `data` folder) |
| `ICHOS_TRADER_OFFLINE=1` | Use the built-in simulated market (same as `--offline`) |
| `ICHOS_PASSCODE`, `ICHOS_GOOGLE_*`, `ICHOS_GITHUB_*`, `ICHOS_OWNER_*`, `ICHOS_PUBLIC_URL` | Logins for a copy other people can open ([CONNECTORS](docs/CONNECTORS.md#logins-for-a-cloud-copy)) |
| `ICHOS_ALPACA_KEY_ID`, `ICHOS_ALPACA_SECRET_KEY`, `ICHOS_ALPACA_LIVE_KEY_ID`, `ICHOS_ALPACA_LIVE_SECRET_KEY`, `ICHOS_ANTHROPIC_API_KEY` | Keys from the environment instead of Setup or the Connectors page |

`run_trader.py` options: `--port 8100`, `--host 127.0.0.1`, `--forever`, `--offline`, `--open`,
`--autostart on|off`. Extra options after `Start Ichos Trader.bat` are passed through.

## What it does

| Part | What it does |
|---|---|
| **Dashboard** | Money and its predicted change, win rate, the ranked markets, biggest increases, what every bot is thinking, who is working, the next plan, predictions (graded after a day) and research |
| **Scanner** | About 200 markets a cycle in parallel, more on a bigger machine; keyless Coinbase and Yahoo prices, or the simulated market |
| **The team** | Scout, strategist (learns before the first buy, then from its own wins and losses), advisor, three traders (one rotates between the strongest coins), a mild skeptic that stops or shrinks fishy buys, a manager that moves money to what works and hires or retires traders, and a researcher |
| **Auto shut-down** | Stops after slow cycles in a row, a drawdown, or a day below where it started; pauses while prices are stale |
| **Speed** | Every cycle is timed per step and graded against what fast means for an internet trader ([DESIGN](docs/DESIGN.md)) |

## Safety

- **Practice by default.** Real money is refused in code (`risk.py`, `connectors/alpaca.py`,
  `realmoney.py`) until the owner switches to it with live keys, a budget and the typed
  confirmation. Practice keys can never move real money.
- **It only uses what you give it.** No borrowing, no short selling, no single market past its
  share, never more than the budget (plus what it earns), and a daily loss limit on real money.
  It only sees and sells what it bought itself, so your own holdings are safe from it.
- **Deny by default.** Every API route needs a signed-in person, and changes need the owner. With
  no login set up it answers only to the PC it runs on. Others can sign in with Google or GitHub to
  see the setup, but never use its keys or its account.

## Troubleshooting

| You see | Do this |
|---|---|
| "Python 3.11 or newer is needed" | Install Python with "Add python.exe to PATH" ticked, then double-click the starter again |
| The page says "can't connect" | The small "Ichos Trader" window was closed: double-click the starter again |
| A yellow **Simulated market** tag | It could not reach the live price feeds; check the internet connection (or you started it with `--offline`) |
| A red banner about Alpaca | Its keys are missing or wrong: re-add the **Paper** keys (practice) or the **live** keys (real money) in Setup |
| "Shut down: real money lost … today" | The daily loss limit stopped it. Press Start the next day, or raise the limit in Setup |
| Port 8100 is busy | Start it with another port: `Start Ichos Trader.bat --port 8101` |

## Developers

```bash
python -m pytest            # from this folder; no network, no keys
python tools/leak_sweep.py  # before every commit (staged changes), or with a base: origin/main
cd web && npm install && npm run build   # after changing web/src; commit web/dist too
```

[docs/API.md](docs/API.md) is the contract between the server and the dashboard.
