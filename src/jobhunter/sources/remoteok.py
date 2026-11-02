"""Remote OK public API. Its terms ask users to link back and credit Remote OK."""
from jobhunter.models import Job, html_to_text

NAME = "remoteok"
MIN_INTERVAL_HOURS = 6
URL = "https://remoteok.com/api"


def parse(data: list[dict]) -> list[Job]:
    jobs = []
    for item in data:
        # The first element is the legal notice, not a job.
        if not item.get("position") or not item.get("url"):
            continue
        jobs.append(
            Job(
                source=NAME,
                url=item["url"],
                company=item.get("company") or "",
                title=item["position"],
                location=item.get("location") or "",
                remote=True,
                description=html_to_text(item.get("description")),
                posted_at=item.get("date"),
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    return parse(http.get_json(URL))
