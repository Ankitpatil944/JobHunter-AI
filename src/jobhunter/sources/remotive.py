"""Remotive public API. Its terms advise at most 4 fetches a day and credit with a link back."""
from jobhunter.models import Job, html_to_text

NAME = "remotive"
MIN_INTERVAL_HOURS = 6
URL = "https://remotive.com/api/remote-jobs"


def parse(data: dict) -> list[Job]:
    return [
        Job(
            source=NAME,
            url=item["url"],
            company=item.get("company_name") or "",
            title=item["title"],
            location=item.get("candidate_required_location") or "",
            remote=True,
            description=html_to_text(item.get("description")),
            posted_at=item.get("publication_date"),
        )
        for item in data.get("jobs", [])
    ]


def fetch(http, companies: dict) -> list[Job]:
    return parse(http.get_json(URL))
