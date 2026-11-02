"""Workday career sites, searched per company from config/companies.yaml.

Workday has no central board. Each company's site has a search endpoint plus one
detail request per job, so details are only fetched for titles that can match.
"""
import httpx

from jobhunter.config import load_yaml
from jobhunter.filter import Rules, title_matches
from jobhunter.models import Job, html_to_text

NAME = "workday"
MIN_INTERVAL_HOURS = 12
QUERIES = ["software engineer", "backend engineer", "data engineer", "machine learning engineer", "AI engineer"]
PAGE_SIZE = 20
MAX_PAGES = 2
MAX_DETAILS_PER_COMPANY = 30


def site_url(company: dict) -> str:
    tenant = company["tenant"]
    return f"https://{tenant}.{company['dc']}.myworkdayjobs.com/wday/cxs/{tenant}/{company['site']}"


def parse_listing(data: dict) -> list[tuple[str, str]]:
    return [(p["title"], p["externalPath"]) for p in data.get("jobPostings") or [] if p.get("externalPath")]


def parse_detail(data: dict, company_name: str) -> Job | None:
    info = data.get("jobPostingInfo") or {}
    url = info.get("externalUrl")
    if not url or not info.get("title"):
        return None
    places = [info.get("location") or ""] + list(info.get("additionalLocations") or [])
    country = (info.get("country") or {}).get("descriptor")
    if country and not any(country in place for place in places):
        places.append(country)
    return Job(
        source=NAME,
        url=url,
        company=company_name,
        title=info["title"],
        location=", ".join(p for p in places if p),
        remote="remote" in (info.get("remoteType") or "").lower(),
        description=html_to_text(info.get("jobDescription")),
        posted_at=info.get("startDate"),
    )


def _matching_paths(http, base: str, rules: Rules) -> list[str]:
    paths: dict[str, None] = {}
    for query in QUERIES:
        for page in range(MAX_PAGES):
            data = http.post_json(
                f"{base}/jobs",
                {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "searchText": query},
            )
            listing = parse_listing(data)
            paths.update((path, None) for title, path in listing if title_matches(title, rules))
            if len(listing) < PAGE_SIZE:
                break
    return list(paths)


def fetch(http, companies: dict) -> list[Job]:
    rules = Rules(load_yaml("search.yaml"))
    jobs: list[Job] = []
    for company in companies.get("workday") or []:
        name = company.get("name") or company["tenant"]
        try:
            base = site_url(company)
            for path in _matching_paths(http, base, rules)[:MAX_DETAILS_PER_COMPANY]:
                job = parse_detail(http.get_json(f"{base}{path}", headers={"Accept": "application/json"}), name)
                if job:
                    jobs.append(job)
        except (httpx.HTTPError, ValueError) as exc:
            http.warn(f"workday/{name}: {str(exc).splitlines()[0][:60]}")
    return jobs
