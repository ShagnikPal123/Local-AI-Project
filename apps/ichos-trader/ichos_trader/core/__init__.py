"""The shared core: pure maths copied from the main app, so the trader imports nothing from it.

* ``indicators`` - trend, momentum, RSI, volatility (from ``trading/signals.py``)
* ``strategies`` - the strategy library and its backtest (from ``finance_lab/strategies.py``)
* ``forecast``   - the price cone and the market mood (from ``finance_lab/forecast.py``)
* ``clock``      - when each market is open (from ``trading/market.py``, plus crypto and currencies)

None of these touch the network or the disk.
"""
