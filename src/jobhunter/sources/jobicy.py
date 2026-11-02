"""Jobicy public API."""
from jobhunter.models import Job, html_to_text

NAME = "jobicy"
MIN_INTERVAL_HOURS = 6
URL = "https://jobicy.com/api/v2/remote-jobs"


def parse(data: dict) -> list[Job]:
    return [
        Job(
            source=NAME,
            url=item["url"],
            company=item.get("companyName") or "",
            title=item["jobTitle"],
            location=item.get("jobGeo") or "",
            remote=True,
            description=html_to_text(item.get("jobDescription")),
            posted_at=item.get("pubDate"),
        )
        for item in data.get("jobs", [])
    ]


def fetch(http, companies: dict) -> list[Job]:
    return parse(http.get_json(URL, params={"count": 100}))
