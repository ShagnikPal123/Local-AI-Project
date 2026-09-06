"Tests for independent-source selection."""

from web_access import _deduplicate_results, _diversify_results

def test_results_prefer_independent_domains():
    results = [
        {"title": "A1", "url": "https://same.example/a"},
        {"title": "B", "url": "https://other.example/b"},
        {"title": "A2", "url": "https://same.example/c"},
    ]
    selected = _diversify_results(_deduplicate_results(results), limit=2)
    assert [item["domain"] for item in selected] == ["same.example", "other.example"]

def test_duplicate_urls_are_removed():
    results = [{"title": "A", "url": "https://example.com"}, {"title": "A copy", "url": "https://example.com"}]
    assert len(_deduplicate_results(results)) == 1
