"""Himalayas public API, read newest first using its cursor pagination."""
from jobhunter.models import Job, epoch_to_iso, html_to_text

NAME = "himalayas"
MIN_INTERVAL_HOURS = 6
URL = "https://himalayas.app/jobs/api"
MAX_PAGES = 25


def parse(data: dict) -> list[Job]:
    jobs = []
    for item in data.get("jobs", []):
        url = item.get("applicationLink") or item.get("guid")
        if not url or not item.get("title"):
            continue
        jobs.append(
            Job(
                source=NAME,
                url=url,
                company=item.get("companyName") or "",
                title=item["title"],
                location=", ".join(item.get("locationRestrictions") or []),
                remote=True,
                description=html_to_text(item.get("description")),
                posted_at=epoch_to_iso(item.get("pubDate")),
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    jobs: list[Job] = []
    params: dict = {"limit": 20}
    for _ in range(MAX_PAGES):
        data = http.get_json(URL, params=params)
        jobs.extend(parse(data))
        cursor = data.get("nextCursor")
        if not cursor:
            break
        params = {"limit": 20, "cursor": cursor}
    return jobs
