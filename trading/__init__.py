"""Trading and finances (Request G1).

The owner: "connects to whatever trading stocks app the user wants… then they can
trade from there and the AI devotes the resources the user wants to predict and
trade stocks. Using searches or know when stocks are moving."

Pieces:

* ``brokers``  — Paper (built in, no money), Alpaca (direct API, paper or live) and
  SnapTrade (one connection to ~20 brokerages: Robinhood, Schwab, Fidelity, Webull,
  E*TRADE, Interactive Brokers…). Apps with no API cannot be traded from here; that
  is said plainly in the UI.
* ``guard``    — the owner's rules every order passes: paper unless live is switched
  on, the AI's budget and limits, approvals, the daily loss stop, Halt.
* ``signals``  — transparent indicators (trend, momentum, RSI, volatility, volume)
  and a track record of how past signals actually did.
* ``autopilot`` — scans the watchlist on the schedule and within the resources the
  owner allots, and proposes or places orders only through ``guard``.

Signals are statistical estimates, not financial advice. Keys live in secret_store.
"""
