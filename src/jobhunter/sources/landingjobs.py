"""Landing.jobs' published Atom feed. Its terms ban scraping the site, so only the feed is read."""
import re

from jobhunter.models import Job, html_to_text
from jobhunter.sources.feeds import read_items

NAME = "landingjobs"
MIN_INTERVAL_HOURS = 6
URL = "https://landing.jobs/feed"
# "At Accenture (Permanent), in Lisbon, Portugal"
OFFER = re.compile(r"At\s+(.+?)\s*(?:\([^)]*\))?\s*,\s+in\s+(.+?)\s*(?:Expires at|Remote policy|$)", re.S)
FULLY_REMOTE = re.compile(r"Remote policy:\s*(Full|Remote)", re.I)


def parse(text: str) -> list[Job]:
    jobs = []
    for entry in read_items(text, "entry"):
        link = entry.find("link")
        title = (entry.findtext("title") or "").strip()
        url = link.get("href", "") if link is not None else ""
        if not title or not url:
            continue
        body = html_to_text(entry.findtext("content"))
        offer = OFFER.search(body)
        jobs.append(
            Job(
                source=NAME,
                url=url,
                company=offer.group(1).strip() if offer else "",
                title=title,
                location=" ".join(offer.group(2).split()) if offer else "",
                remote=bool(FULLY_REMOTE.search(body)),
                description=body,
                posted_at=entry.findtext("published"),
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    return parse(http.get_text(URL))
