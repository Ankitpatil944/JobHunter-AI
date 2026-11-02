"""We Work Remotely RSS feed. Item titles look like 'Company: Role'."""
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from jobhunter.models import Job, html_to_text

NAME = "weworkremotely"
MIN_INTERVAL_HOURS = 6
URL = "https://weworkremotely.com/remote-jobs.rss"


def _iso(value: str | None) -> str | None:
    try:
        return parsedate_to_datetime(value).isoformat() if value else None
    except (TypeError, ValueError):
        return None


def parse(text: str) -> list[Job]:
    jobs = []
    for item in ET.fromstring(text).iter("item"):
        heading = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not heading or not url:
            continue
        company, sep, title = heading.partition(":")
        if not sep:
            company, title = "", heading
        jobs.append(
            Job(
                source=NAME,
                url=url,
                company=company.strip(),
                title=title.strip(),
                location=(item.findtext("region") or "").strip(),
                remote=True,
                description=html_to_text(item.findtext("description")),
                posted_at=_iso(item.findtext("pubDate")),
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    return parse(http.get_text(URL))
