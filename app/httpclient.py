"""One small helper every provider that talks over HTTP uses (weather, web search)."""
import httpx


class http_client:
    """`async with http_client(http) as client`: the caller's client if given (left open), else a fresh one."""
    def __init__(self, client=None):
        self.client, self.own = client, client is None

    async def __aenter__(self):
        if self.own:
            self.client = httpx.AsyncClient()
        return self.client

    async def __aexit__(self, *exc):
        if self.own:
            await self.client.aclose()
        return False
