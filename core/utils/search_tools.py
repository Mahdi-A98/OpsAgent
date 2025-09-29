import requests
from langchain.tools import tool
from langchain_tavily import TavilySearch
from langchain_google_community import GoogleSearchResults, GoogleSearchAPIWrapper
from core.settings import TAVILY_API_KEY, GOOGLE_API_KEY, GOOGLE_SEARCH_ENGINE_ID, OPENAI_API_KEY


google_search_api_wrapper = GoogleSearchAPIWrapper(
    google_api_key = GOOGLE_API_KEY,
    google_cse_id = GOOGLE_SEARCH_ENGINE_ID
)

google_search = GoogleSearchResults(
    api_wrapper=google_search_api_wrapper
)


tavily_search = TavilySearch(
    api_key=TAVILY_API_KEY,
    max_results=3
)

@tool("url_extractor", return_direct=False)
def url_extractor(url: str) -> str:
    """extract url info."""
    # Placeholder implementation
    return requests.get(url).content.decode()


@tool("search_web", return_direct=False)
def search_web(query: str) -> str:
    """
    Search the web for the given query using DuckDuckGo instant API.

    Args:
        query (str): Search query.

    Returns:
        str: Search results or summary text.
    """
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": 1}
        resp = requests.get(url, params=params)
        data = resp.json()

        if data.get("AbstractText"):
            return f"Top result: {data['AbstractText']}"
        elif data.get("RelatedTopics"):
            top_topics = [t.get("Text") for t in data["RelatedTopics"][:3] if "Text" in t]
            return " | ".join(top_topics)
        else:
            return "No clear result found."
    except Exception as e:
        return f"❌ Search failed: {str(e)}"
