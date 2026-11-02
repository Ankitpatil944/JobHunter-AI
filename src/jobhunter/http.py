"""A polite HTTP client: identifies itself, spaces out requests and retries briefly."""
import time

import httpx

USER_AGENT = "jobhunter/0.1 (personal job search tool)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class Http:
    def __init__(self, delay: float = 1.0, retries: int = 2, timeout: float = 30.0, transport=None):
        self.delay = delay
        self.retries = retries
        self.warnings: list[str] = []
        self._last = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=timeout,
            transport=transport,
        )

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def _get(self, url: str, **kwargs) -> httpx.Response:
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                response = self._client.get(url, **kwargs)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
                time.sleep(2 ** attempt)
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.retries:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("unreachable")

    def get_json(self, url: str, **kwargs):
        return self._get(url, **kwargs).json()

    def get_text(self, url: str, **kwargs) -> str:
        return self._get(url, **kwargs).text

    def close(self) -> None:
        self._client.close()
