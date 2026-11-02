"""Greenhouse public job board API, read per company from config/companies.yaml."""
import re

import httpx

from jobhunter.models import Job, html_to_text

NAME = "greenhouse"
MIN_INTERVAL_HOURS = 6
URL = "https://boards-api.greenhouse.io/v1/boards/{}/jobs"
# Companies host job pages on their own sites, but this form address works for all of them.
APPLY_URL = "https://job-boards.greenhouse.io/embed/job_app?for={}&token={}"
REMOTE = re.compile(r"\bremote\b", re.I)


def parse(data: dict, slug: str) -> list[Job]:
    jobs = []
    for item in data.get("jobs", []):
        location = (item.get("location") or {}).get("name") or ""
        jobs.append(
            Job(
                source=NAME,
                url=item["absolute_url"],
                company=item.get("company_name") or slug,
                title=item["title"],
                location=location,
                remote=bool(REMOTE.search(location)),
                description=html_to_text(item.get("content")),
                posted_at=item.get("first_published") or item.get("updated_at"),
                apply_url=APPLY_URL.format(slug, item.get("id")),
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    jobs: list[Job] = []
    for slug in companies.get("greenhouse") or []:
        try:
            jobs.extend(parse(http.get_json(URL.format(slug), params={"content": "true"}), slug))
        except (httpx.HTTPError, ValueError) as exc:
            http.warn(f"greenhouse/{slug}: {str(exc).splitlines()[0][:60]}")
    return jobs
