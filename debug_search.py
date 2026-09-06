
from web_access import search_results

def test_search():
    query = "current president of the United States"
    print(f"Searching for: {query}")
    
    # Test with default (any)
    results = search_results(query, engine="duckgo", freshness="any")
    print("\n--- DuckDuckGo (any) ---")
    for r in results[:3]:
        print(f"Title: {r['title']}\nURL: {r['url']}\n")

    # Test with week
    results = search_results(query, engine="duckgo", freshness="week")
    print("\n--- DuckDuckGo (week) ---")
    for r in results[:3]:
        print(f"Title: {r['title']}\nURL: {r['url']}\n")

if __name__ == "__main__":
    test_search()
