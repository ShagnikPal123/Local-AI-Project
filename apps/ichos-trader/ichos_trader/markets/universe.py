"""The markets the scout looks at: hundreds of them, across stocks, crypto and currencies.

Shagnik: "Instead of looking at one market it can look at hundreds and make decisions off those."
These lists are the starting set that works offline. When the internet is there, the crypto feed
adds every live USD pair the exchange lists, so the real count is higher.

The stock list starts from the main app's stock adder universe (``trading/discovery.py``) and adds
more large, liquid names: a scout that ranks on liquidity should start where liquidity is.
"""

from __future__ import annotations

from typing import Dict, List

from ..models import Instrument

ETFS = ["SPY", "QQQ", "IWM", "DIA", "VTI", "EFA", "EEM", "TLT", "GLD", "SLV", "XLK", "XLF", "XLE", "XLV", "XLI",
        "XLY", "XLP", "XLU", "SMH", "XLC", "XLB", "ARKK", "HYG", "USO"]

STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX", "CRM", "ORCL", "ADBE", "INTC",
    "QCOM", "TXN", "MU", "PLTR", "SHOP", "UBER", "ABNB", "PYPL", "COIN", "CRWD", "PANW", "NOW", "ANET", "TSM",
    "ASML", "ARM", "AMAT", "LRCX", "SNOW", "DDOG", "NET", "MRVL", "KLAC", "ADI", "IBM", "CSCO", "DELL", "HPQ",
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "SCHW", "BLK", "C", "SOFI", "HOOD",
    "XOM", "CVX", "COP", "CAT", "DE", "BA", "GE", "HON", "LMT", "RTX", "UPS", "FCX", "OXY", "SLB",
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ISRG", "NVO", "AMGN", "GILD", "CVS",
    "HD", "LOW", "COST", "WMT", "TGT", "NKE", "MCD", "SBUX", "KO", "PEP", "PG", "DIS", "CMG", "LULU",
    "T", "VZ", "TMUS", "NEE", "DUK", "SO", "SPOT", "RBLX", "MSTR", "RIVN", "LCID", "F", "GM", "BABA", "PDD",
]

CRYPTO: Dict[str, str] = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "XRP", "ADA": "Cardano", "DOGE": "Dogecoin",
    "AVAX": "Avalanche", "LINK": "Chainlink", "DOT": "Polkadot", "LTC": "Litecoin", "BCH": "Bitcoin Cash",
    "SHIB": "Shiba Inu", "UNI": "Uniswap", "ATOM": "Cosmos", "XLM": "Stellar", "ETC": "Ethereum Classic",
    "FIL": "Filecoin", "APT": "Aptos", "ARB": "Arbitrum", "OP": "Optimism", "NEAR": "NEAR", "ICP": "Internet Computer",
    "HBAR": "Hedera", "AAVE": "Aave", "MKR": "Maker", "SUI": "Sui", "INJ": "Injective", "RNDR": "Render",
    "GRT": "The Graph", "ALGO": "Algorand", "SAND": "The Sandbox", "MANA": "Decentraland", "AXS": "Axie Infinity",
    "CRV": "Curve", "LDO": "Lido", "STX": "Stacks", "IMX": "Immutable", "SEI": "Sei", "TIA": "Celestia",
    "PEPE": "Pepe", "BONK": "Bonk", "WIF": "dogwifhat", "FET": "Fetch.ai", "XTZ": "Tezos", "EOS": "EOS",
    "COMP": "Compound", "SNX": "Synthetix", "1INCH": "1inch", "ZEC": "Zcash", "DASH": "Dash", "CHZ": "Chiliz",
    "ENS": "ENS", "BAT": "Basic Attention", "KSM": "Kusama", "MINA": "Mina", "JASMY": "JasmyCoin",
}

FX = ["EUR-USD", "GBP-USD", "USD-JPY", "USD-CHF", "AUD-USD", "USD-CAD", "NZD-USD", "EUR-GBP", "EUR-JPY", "GBP-JPY",
      "EUR-CHF", "AUD-JPY", "USD-MXN", "USD-INR", "USD-CNY", "USD-SGD", "USD-HKD", "USD-SEK", "USD-NOK", "USD-ZAR"]


def stocks() -> List[Instrument]:
    return ([Instrument(s, "etf", s, "USD", "yahoo") for s in ETFS]
            + [Instrument(s, "stock", s, "USD", "yahoo") for s in STOCKS])


def crypto() -> List[Instrument]:
    return [Instrument(f"{code}-USD", "crypto", name, "USD", "coinbase") for code, name in CRYPTO.items()]


def fx() -> List[Instrument]:
    return [Instrument(pair, "fx", pair.replace("-", "/"), pair.split("-")[1], "yahoo") for pair in FX]


def everything() -> List[Instrument]:
    return stocks() + crypto() + fx()
