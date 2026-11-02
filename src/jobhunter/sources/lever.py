"""Lever public postings API, read per company from config/companies.yaml."""
import httpx

from jobhunter.models import Job, epoch_to_iso, html_to_text

NAME = "lever"
MIN_INTERVAL_HOURS = 6
URL = "https://api.lever.co/v0/postings/{}"


def _description(item: dict) -> str:
    parts = [item.get("descriptionPlain") or ""]
    for section in item.get("lists") or []:
        parts += [section.get("text") or "", html_to_text(section.get("content"))]
    parts.append(item.get("additionalPlain") or "")
    return "\n\n".join(p for p in parts if p)


def parse(data: list[dict], slug: str) -> list[Job]:
    jobs = []
    for item in data:
        categories = item.get("categories") or {}
        places = categories.get("allLocations") or [categories.get("location") or ""]
        # Lever gives createdAt in milliseconds.
        created = item.get("createdAt")
        jobs.append(
            Job(
                source=NAME,
                url=item["hostedUrl"],
                company=slug,
                title=item["text"].strip(),
                location=", ".join(p for p in places if p),
                remote=item.get("workplaceType") == "remote",
                description=_description(item),
                posted_at=epoch_to_iso(created // 1000) if created else None,
                apply_url=item.get("applyUrl") or "",
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    jobs: list[Job] = []
    for slug in companies.get("lever") or []:
        try:
            jobs.extend(parse(http.get_json(URL.format(slug), params={"mode": "json"}), slug))
        except (httpx.HTTPError, ValueError) as exc:
            http.warn(f"lever/{slug}: {str(exc).splitlines()[0][:60]}")
    return jobs
