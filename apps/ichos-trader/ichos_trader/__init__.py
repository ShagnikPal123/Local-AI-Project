"""Ichos Trader: the trading desk from Nyx Ichos, split out to run on its own.

The owner (Fixer Upper doc, page 3): "split off the trading agent into a separate app which uses our
model but since it is separated it can run much faster". This package is that app. It imports
nothing from the main Nyx app, so the folder can move to its own GitHub repo unchanged.

The parts, in the order a trade goes through them:

* ``markets``     - prices, candles and order books for stocks, crypto and currencies (or a
  built-in simulated market when there is no internet).
* ``ranking``     - scores every market on liquidity, spread, depth and order flow.
* ``team``        - the bots: scout, strategist, traders, advisor, mild skeptic, manager.
* ``risk`` / ``paper`` - its own money only, and a practice account with real-world costs.
* ``engine``      - the loop that runs it all 24/7, with ``watchdog`` shutting it down when it is
  slow or losing, and ``latency`` timing every step.
* ``access`` / ``connectors`` - who may use it (local, Google or GitHub login), brokers, models,
  and the Claude connector that is only used when asked.
* ``server``      - the web API and the dashboard.

Practice money by default; real money only after the owner switches to it in Setup (see ``realmoney``).
"""

__version__ = "0.1.0"
