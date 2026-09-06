"""Tests for the finance connector, permanent financial knowledge, and advisor mode."""

from unittest.mock import MagicMock, patch

from attributes import get_attribute
from connectors.finance_connector import FinanceConnector
from fastapi.testclient import TestClient

from finance import advisor_context, get_finance_knowledge
from server import app
from tools import TOOL_REGISTRY

client = TestClient(app)

QUOTE_CSV = """Symbol,Date,Time,Open,High,Low,Close,Volume
aapl.us,2024-01-02,22:30:01,192.53,194.99,191.8,194.98,12345678
msft.us,2024-01-02,22:30:02,370.1,376.5,368.9,375.8,9876543
"""

HISTORY_CSV = """Date,Open,High,Low,Close,Volume
2023-10-02,170.0,172.5,169.1,171.2,1000000
2023-10-03,171.5,173.0,170.2,172.8,1100000
2023-10-04,172.0,174.1,171.3,173.5,1050000
"""


# ---------------------------------------------------------------------------
# Connector parsing (pure, offline)
# ---------------------------------------------------------------------------


def test_parse_quote_csv():
    rows = FinanceConnector.parse_quote_csv(QUOTE_CSV)
    assert len(rows) == 2
    assert rows[0]["symbol"] == "aapl.us"
    assert rows[0]["close"] == 194.98
    assert rows[1]["close"] == 375.8


def test_parse_quote_csv_ignores_bad_rows():
    rows = FinanceConnector.parse_quote_csv("Symbol,Date,Time,Open,High,Low,Close,Volume\nzzz.us,,,,,N/D,\n")
    assert rows == []


def test_parse_history_csv():
    rows = FinanceConnector.parse_history_csv(HISTORY_CSV)
    assert len(rows) == 3
    assert rows[0]["date"] == "2023-10-02"
    assert rows[-1]["close"] == 173.5


def test_normalize_symbol():
    assert FinanceConnector.normalize_symbol("aapl") == "AAPL"
    assert FinanceConnector.normalize_symbol("BTC-USD") == "BTC-USD"
    assert FinanceConnector.normalize_symbol("") == ""


YAHOO_QUOTE = {
    "chart": {
        "result": [
            {
                "meta": {
                    "symbol": "AAPL",
                    "regularMarketPrice": 194.98,
                    "chartPreviousClose": 192.0,
                    "regularMarketTime": 1704186000,
                    "currency": "USD",
                }
            }
        ]
    }
}

YAHOO_HISTORY = {
    "chart": {
        "result": [
            {
                "timestamp": [1704067200, 1704153600],
                "indicators": {
                    "quote": [
                        {
                            "open": [192.0, 193.0],
                            "high": [195.0, 196.0],
                            "low": [191.0, 192.0],
                            "close": [194.0, 194.98],
                            "volume": [1000000, 1100000],
                        }
                    ]
                },
            }
        ]
    }
}


def test_parse_yahoo_quote():
    rows = FinanceConnector.parse_yahoo_quote(YAHOO_QUOTE)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["close"] == 194.98
    assert rows[0]["previous_close"] == 192.0


def test_parse_yahoo_history():
    rows = FinanceConnector.parse_yahoo_history(YAHOO_HISTORY)
    assert len(rows) == 2
    assert rows[-1]["date"] == "2024-01-02"
    assert rows[-1]["close"] == 194.98
    assert rows[-1]["high"] == 196.0


def test_parse_yahoo_empty_payload():
    assert FinanceConnector.parse_yahoo_quote({"chart": {}}) == []
    assert FinanceConnector.parse_yahoo_history({"chart": {}}) == []


def test_market_status_shape():
    result = FinanceConnector().market_status()
    assert result["success"] is True
    assert isinstance(result["open"], bool)


# ---------------------------------------------------------------------------
# Permanent financial knowledge
# ---------------------------------------------------------------------------


def test_finance_knowledge_loads_sections():
    knowledge = get_finance_knowledge()
    assert knowledge.chunks
    assert "Valuation Ratios & Fundamentals" in knowledge.sections
    assert "When to Consider Selling" in knowledge.sections


def test_finance_knowledge_search_pe_ratio():
    results = get_finance_knowledge().search("P/E ratio")
    assert results
    assert results[0]["section"] == "Valuation Ratios & Fundamentals"


def test_finance_knowledge_search_when_to_sell():
    results = get_finance_knowledge().search("when should I sell my stock")
    assert results
    assert "When to Consider Selling" in [r["section"] for r in results[:3]]


def test_finance_knowledge_search_dca():
    results = get_finance_knowledge().search("dollar cost averaging")
    assert results
    assert results[0]["section"] == "Market Basics"


def test_finance_knowledge_has_disclaimer():
    text = "\n".join(chunk["text"] for chunk in get_finance_knowledge().chunks)
    assert "not personalized" in text.lower()


# ---------------------------------------------------------------------------
# Advisor context (personal permanent memory)
# ---------------------------------------------------------------------------


def test_advisor_context_includes_personal_memory():
    memory = MagicMock()
    memory.get_important.return_value = [
        {"topic": "portfolio", "content": "I hold AAPL, MSFT, and an S&P 500 ETF."},
        {"topic": "favorite color", "content": "deep blue"},
    ]
    context = advisor_context("should I add to my portfolio?", memory=memory)
    assert "AAPL" in context
    assert "favorite color" not in context


def test_advisor_context_works_without_memory():
    context = advisor_context("what is a good P/E ratio?")
    assert "Relevant financial knowledge" in context


# ---------------------------------------------------------------------------
# Finance attribute (mode) and tools
# ---------------------------------------------------------------------------


def test_finance_attribute_exists():
    attribute = get_attribute("finance")
    assert attribute.display_name == "Finance Advisor"
    assert "stock_quote" in attribute.system_guidance


def test_finance_tools_registered():
    names = {tool.name for tool in TOOL_REGISTRY.list_tools()}
    assert {"stock_quote", "stock_history", "market_status", "search_finance_knowledge"} <= names


# ---------------------------------------------------------------------------
# Server endpoints
# ---------------------------------------------------------------------------


def test_finance_quote_endpoint_mocked():
    with patch("connectors.CONNECTOR_REGISTRY.execute", return_value={
        "success": True, "source": "stooq",
        "quotes": [{"symbol": "aapl.us", "date": "2024-01-02", "close": 194.98, "open": 192.53}],
    }):
        response = client.get("/api/finance/quote", params={"symbols": "AAPL"})
    assert response.status_code == 200
    assert response.json()["quotes"][0]["close"] == 194.98


def test_finance_history_endpoint_mocked():
    with patch("connectors.CONNECTOR_REGISTRY.execute", return_value={
        "success": True, "symbol": "aapl.us", "range": "1mo",
        "rows": [{"date": "2024-01-02", "close": 194.98}],
    }):
        response = client.get("/api/finance/history", params={"symbol": "AAPL", "range": "1mo"})
    assert response.status_code == 200
    assert response.json()["rows"][0]["close"] == 194.98


def test_finance_knowledge_endpoint():
    response = client.get("/api/finance/knowledge", params={"q": "P/E ratio"})
    assert response.status_code == 200
    assert response.json()["results"][0]["section"] == "Valuation Ratios & Fundamentals"


def test_finance_advice_endpoint_uses_finance_attribute():
    with patch("server._get_service") as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.memory.get_important.return_value = []
        mock_svc.chat.return_value = ("guidance with disclaimer", "ollama")
        mock_get_svc.return_value = mock_svc

        response = client.post(
            "/api/finance/advice",
            json={"question": "Should I buy more AAPL?", "chat_id": "fin-room"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "guidance with disclaimer"
        assert data["chat_id"] == "fin-room"
        # The finance attribute was applied to the chat.
        _, kwargs = mock_svc.chat.call_args
        assert kwargs["attribute_id"] == "finance"
