# Connectors

What the trader can plug into, which ones are recommended, and why. Every key is saved in
`data/secrets.json` (gitignored) or read from an environment variable (`ICHOS_<NAME>`), and only
ever shown back masked to its last 4 characters. Viewers see that a key is set, not any of it.

## Brokers

| Broker | Markets | Practice account | Status | Why |
|---|---|---|---|---|
| **Alpaca** (recommended) | US stocks, ETFs, crypto | Free, real prices | Wired (practice, and real money behind the Setup switch) | One free API for most of what the scanner ranks |
| Kraken | Crypto | No separate one | Planned | Low fees and many coins, once crypto needs its own broker |
| OANDA | Currencies | Free | Planned | The cleanest practice FX account |
| Interactive Brokers | Nearly everything | Yes | Planned | Widest reach, but needs their gateway app running |

The built-in **practice account** (`paper.py`) is the default and needs nothing. Alpaca talks to
`paper-api.alpaca.markets` with the practice keys. It uses the live address only with the separate
`alpaca_live` keys, after the owner switches to real money in Setup with a budget and the typed
confirmation (`realmoney.py`).

## Market data

| Feed | Markets | Key | Notes |
|---|---|---|---|
| Coinbase | Crypto prices, candles, order book | None | Real bid/ask and depth for the ranking |
| Yahoo | Stocks, ETFs, currencies | None | Fine for a scan every minute; not for high-speed trading |
| Simulated | Everything | None | `--offline` or `ICHOS_TRADER_OFFLINE=1`; the dashboard says "simulated" |

## Models

| Model | Cost | When it is used |
|---|---|---|
| Ollama (local) | Free | Shown when it runs on the PC; nothing calls it on a timer yet |
| Claude | Paid per question | **Only** when the owner switches the connector on *and* presses Ask. The trader never calls it by itself. It is sent a key-free summary of the dashboard. |

## Logins (for a cloud copy)

| Login | Set with | Who is the owner |
|---|---|---|
| Local (default) | nothing | Only the PC it runs on (127.0.0.1); everyone else is refused |
| Passcode | `ICHOS_PASSCODE` or the Connectors page | Whoever knows it (12+ characters, locks for 10 minutes after 5 wrong tries) |
| Google | `ICHOS_GOOGLE_CLIENT_ID` + `ICHOS_GOOGLE_CLIENT_SECRET` | Addresses in `ICHOS_OWNER_EMAILS` |
| GitHub | `ICHOS_GITHUB_CLIENT_ID` + `ICHOS_GITHUB_CLIENT_SECRET` | Names in `ICHOS_OWNER_GITHUB` |

Anyone else who signs in is a **viewer**: they see the setup and the dashboard, and every change,
key and order is refused. Set `ICHOS_PUBLIC_URL` (for example `https://trader.example.com`) so the
login callback address is right behind a proxy; the OAuth app's callback is
`<ICHOS_PUBLIC_URL>/api/auth/callback/google` (or `/github`).
