"""Ashby public job board API, read per company from config/companies.yaml."""
import httpx

from jobhunter.models import Job

NAME = "ashby"
MIN_INTERVAL_HOURS = 6
URL = "https://api.ashbyhq.com/posting-api/job-board/{}"


def parse(data: dict, slug: str) -> list[Job]:
    jobs = []
    for item in data.get("jobs", []):
        if item.get("isListed") is False:
            continue
        places = [item.get("location") or ""]
        places += [p.get("location") or "" for p in item.get("secondaryLocations") or []]
        jobs.append(
            Job(
                source=NAME,
                url=item["jobUrl"],
                company=slug,
                title=item["title"].strip(),
                location=", ".join(p for p in places if p),
                remote=bool(item.get("isRemote")) or item.get("workplaceType") == "Remote",
                description=item.get("descriptionPlain") or "",
                posted_at=item.get("publishedAt"),
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    jobs: list[Job] = []
    for slug in companies.get("ashby") or []:
        try:
            jobs.extend(parse(http.get_json(URL.format(slug)), slug))
        except (httpx.HTTPError, ValueError) as exc:
            http.warn(f"ashby/{slug}: {str(exc).splitlines()[0][:60]}")
    return jobs
