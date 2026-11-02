"""Arbeitnow public API, mostly Germany and Europe."""
from jobhunter.models import Job, epoch_to_iso, html_to_text

NAME = "arbeitnow"
MIN_INTERVAL_HOURS = 6
URL = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 5


def parse(data: dict) -> list[Job]:
    return [
        Job(
            source=NAME,
            url=item["url"],
            company=item.get("company_name") or "",
            title=item["title"],
            location=item.get("location") or "",
            remote=bool(item.get("remote")),
            description=html_to_text(item.get("description")),
            posted_at=epoch_to_iso(item.get("created_at")),
        )
        for item in data.get("data", [])
    ]


def fetch(http, companies: dict) -> list[Job]:
    jobs: list[Job] = []
    for page in range(1, MAX_PAGES + 1):
        data = http.get_json(URL, params={"page": page})
        jobs.extend(parse(data))
        if not (data.get("links") or {}).get("next"):
            break
    return jobs
