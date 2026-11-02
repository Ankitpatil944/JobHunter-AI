"""The common job record and the keys used to remove duplicates."""
import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

TRACKING_PARAMS = {"ref", "source", "src", "gclid", "fbclid", "lever-source", "gh_src"}
COMPANY_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|limited|pvt|private|corp|corporation|gmbh|co)\b\.?", re.I
)


@dataclass
class Job:
    source: str
    url: str
    company: str
    title: str
    location: str = ""
    remote: bool = False
    description: str = ""
    posted_at: str | None = None
    apply_url: str = ""

    @property
    def url_key(self) -> str:
        return normalize_url(self.url)

    @property
    def content_key(self) -> str:
        parts = (normalize_company(self.company), _squash(self.title), _squash(self.location))
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def normalize_company(name: str) -> str:
    return _squash(COMPANY_SUFFIXES.sub(" ", name or ""))


def normalize_url(url: str) -> str:
    """Lowercase the host and drop tracking params, keeping params that identify a job."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), "")
    )


def html_to_text(markup: str | None) -> str:
    if not markup:
        return ""
    # Greenhouse escapes its HTML, so unescape before parsing.
    text = BeautifulSoup(html.unescape(markup), "html.parser").get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def epoch_to_iso(value: int | float | str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None
