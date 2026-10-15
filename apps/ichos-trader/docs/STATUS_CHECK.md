# Trader split: what was already built (checked 2026-10-13)

Every ask from the Fixer Upper doc's trading section (pages 3–4) and the "Trading follows the colours" fix (page 33),
checked against the code and git history of `Local-AI-Project` at `93dc0be`. Each one says **Done**, **Partial** or
**Not started**, with where the proof is.

The short version: the old Trading tab already has a real practice account, a team of up to 8 strategy traders, a
hands-off Adaptive mode, a stock adder and a 24/7 run mode. What it does not have is everything that makes it its own
app: crypto and other markets, ranking by liquidity / spread / depth / order flow, named bot roles (manager, advisor,
skeptic), a dashboard, auto shut-down, speed tests, login for cloud use, and the redesign.

| # | Ask (his words, shortened) | Status | Proof |
|---|---|---|---|
| 1 | Split the trader into its own app | Not started | No separate app or folder; trading lives in `trading/`, `finance_lab/`, `routes_trading.py` |
| 2 | Post to GitHub and link from the main README: "this is where the trader went" | Not started | `README.md:54` still lists "Trading practice" as a tab |
| 3 | Dashboard: markets, increases, what it's thinking, how many agents run, next plan, predictions, money increase, predicted increase, research, win rate | Partial | Pieces exist on different cards: account and P/L (`brokers.py` `PaperBroker.stats`), win rate (`stats()["win_rate"]`), signal hit rate (`signals.score_track_record`), next scan time (`autopilot.run_status`), desk agents (`panels/trading/DeskCard.tsx`), research note (`autopilot.research`). No single dashboard, no predicted increase on screen (`finance_lab/forecast.py` can make one), no live "thinking" feed |
| 4 | Look at hundreds of markets, not one | Partial | `trading/discovery.py` has a ~97-stock universe looked at 20 at a time (`SLICE = 20`); the watchlist caps at 40 (`guard.py` `watchlist_max`) |
| 5 | Its own ranking by liquidity, spread, market depth and order flow | Not started | Ranking is indicator score × confidence × track record (`signals.rank_watchlist`); volume is only a note ("Volume 2× normal") in `signals.analyse` |
| 6 | Focus on the best strategies; better after a day of running | Partial | The desk moves money from the worst trader to the best every 12 runs (`trading/desk.py:258` `rebalance`); the finance lab trains strategies per market mood (`finance_lab/simulator.py`, `memory.py`) but the desk does not read that memory |
| 7 | Rotate between Bitcoin, Ethereum and similar | Not started | No crypto anywhere; rotation exists only between stocks (`allocator.should_rotate`) |
| 8 | Any market, any currency | Not started | US stocks in dollars only (`market.py` uses the stock feed; `account()` returns `"currency": "USD"`) |
| 9 | Run 24/7 | Done | Run modes market / always / until (`trading/autopilot.py:39`), restarts itself when the engine starts (`ensure_running`) |
| 10 | Auto shut-down when slow or losing | Partial | Daily loss stop blocks new buys (`guard.py` `daily_loss_stop_pct`) and Halt exists; nothing watches speed, and nothing stops a trader that keeps losing over days |
| 11 | Its own big team; many trades at once | Partial | Up to 8 desk traders, each with a strategy, a market and its own pot (`trading/desk.py:41-49`) |
| 12 | Bot roles: mild skeptic, manager, advisor and more | Not started | Closest thing is the news check that can say AVOID (`autopilot.research`, `read_verdict`); no named roles |
| 13 | Adds bots by itself when the analysis says so | Not started | Desk traders are only added by the owner (`desk.configure`) |
| 14 | Background agents shown making strategies and working | Partial | The finance lab lights up pipeline nodes as they run (`finance_lab/node_map.py`); no live activity feed of bots |
| 15 | Learn first: understand trading and the market, practice with fake money first | Partial | Practice account with real-world fills, spread and slippage (`brokers.py` `PaperBroker`, `fill_price`); walk-forward training (`finance_lab/simulator.py`). Nothing makes the trader study before it may trade |
| 16 | Fully auto by default; owner only turns it on and off | Partial | Adaptive mode chooses every setting (`trading/adaptive.py`), but it is off by default and approval defaults to "always ask" (`guard.py` `default_settings`) |
| 17 | Tuning section: buttons, dials, bars, graphs | Partial | Adaptive card with pins (`panels/trading/AdaptiveCard.tsx`) and number fields; no dials or graphs |
| 18 | Best free models, local and cloud | Partial | Local first rule (`finance_lab/model_policy.py`); research uses the main app's fast chat role (`autopilot.research`). Ties to the main app's model router |
| 19 | Test the agent's speed; decide what "fast" means in trading | Not started | No timing of the trading path anywhere |
| 20 | Works without his computer (cloud), or anti-crash and stay-on if local | Partial | Local only. The main app's launcher restarts the engine (`launcher.py`); the trader has no watchdog of its own |
| 21 | Cloud login with Google or GitHub; others can see the setup but never use his keys or account | Not started | The main app has its own local logins (`auth.py`); nothing for a hosted trader |
| 22 | Connect to the right apps and tell him what is best | Partial | Paper, Alpaca and SnapTrade (`trading/brokers.py:380`); no crypto exchange, no recommendation written down |
| 23 | A Claude connector, used only when he asks | Not started | The main app has `claude_bridge.py`; the trader has none |
| 24 | Profit pays for the subscription ("self-growing business") | Not started | Needs real money; waits for his word (see below) |
| 25 | Redesign: new look and style | Not started | Same look as the rest of the app (`panels/trading/trading.css`) |
| 26 | Trading follows the chosen colours (page 33) | Partial | `trading.css` uses theme variables in 22 places but also hard-coded greys (`#a1a1aa`, `#0e0e13`…) |

## What waits for the owner

- **Real money** (live broker accounts, and the "pays for the subscription" idea). Paper only until he says so.
- **A hosted (cloud) copy**, and the Google / GitHub login apps it needs. The login code is built and tested; turning
  it on needs him to create the login app and pick where it runs.
- **Its own GitHub repo.** It is built as a folder that can move to its own repo unchanged.
