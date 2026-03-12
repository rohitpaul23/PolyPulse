import os
from langchain_community.tools.tavily_search import TavilySearchResults
from duckduckgo_search import DDGS
from typing import List, Dict

def get_tavily_search_tool(max_results=20):
    """Returns a Tavily search tool instance, if API key is available."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return None
    return TavilySearchResults(max_results=max_results)

def search_duckduckgo(query: str, max_results=20) -> List[Dict]:
    """Fallback DuckDuckGo search returning structured dicts."""
    results = []
    try:
        with DDGS() as ddgs:
            # ddgs.text yields dictionaries like {'title': '...', 'href': '...', 'body': '...'}
            results = [r for r in ddgs.text(query, max_results=max_results)]
    except Exception as e:
        print(f"DuckDuckGo search failed: {e}")
    return results

def search_news(query: str, max_results=20) -> List[Dict]:
    """
    Search for news using Tavily if available, else DuckDuckGo.
    Returns a unified format: list of dicts with 'url', 'content', 'title' or 'snippet'
    """
    tavily_tool = get_tavily_search_tool(max_results=max_results)
    if tavily_tool:
        try:
            # Tavily returns a list of matching dicts
            return tavily_tool.invoke({"query": query})
        except Exception as e:
            print(f"Tavily search failed, falling back to DDG: {e}")
            
    # Fallback to DDG
    ddg_res = search_duckduckgo(query, max_results=max_results)
    formatted = []
    for r in ddg_res:
        formatted.append({
            "url": r.get('href'),
            "content": r.get('body'),
            "title": r.get('title')
        })
    return formatted
