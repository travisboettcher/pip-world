"""The Tavily web search provider."""
from .httpclient import http_client
from .search import Answers, Found, register


@register("tavily")
class Tavily:
    URL = "https://api.tavily.com/search"

    def __init__(self, settings):
        self.key = settings.tavily_api_key

    @property
    def ready(self) -> bool:
        return bool(self.key)

    async def fetch(self, query: str, http=None) -> Answers:
        async with http_client(http) as client:
            r = await client.post(self.URL, json={"api_key": self.key, "query": str(query), "max_results": 3, "include_answer": True},
                                  timeout=30)
            r.raise_for_status()
        d = r.json()
        return Answers(d.get("answer") or "", [Found(x.get("title") or "", x.get("content") or "") for x in d.get("results", [])])
