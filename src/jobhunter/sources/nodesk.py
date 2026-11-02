"""NoDesk's published RSS feed for engineering jobs. Item titles look like 'Role at Company'."""
from jobhunter.models import Job, html_to_text
from jobhunter.sources.feeds import read_items, rfc822_to_iso

NAME = "nodesk"
MIN_INTERVAL_HOURS = 6
URL = "https://nodesk.co/remote-jobs/engineering/index.xml"


def parse(text: str) -> list[Job]:
    jobs = []
    for item in read_items(text, "item"):
        heading = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        title, sep, company = heading.rpartition(" at ")
        if not sep or not url:
            continue
        jobs.append(
            Job(
                source=NAME,
                url=url,
                company=company.strip(),
                title=html_to_text(title),
                remote=True,
                description=html_to_text(item.findtext("description")),
                posted_at=rfc822_to_iso(item.findtext("pubDate")),
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    return parse(http.get_text(URL))
