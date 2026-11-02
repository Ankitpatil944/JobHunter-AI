"""Hacker News 'Who is hiring?' threads, read through the Algolia API.

Posts are free text, conventionally headed 'Company | Role | Location | REMOTE'.
"""
import re

from jobhunter.models import Job, html_to_text

NAME = "hackernews"
MIN_INTERVAL_HOURS = 12
SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{}"
REMOTE = re.compile(r"\bremote\b", re.I)


def parse_thread(thread: dict) -> list[Job]:
    jobs = []
    for comment in thread.get("children", []):
        text = html_to_text(comment.get("text"))
        if not text:
            continue
        header = text.split("\n", 1)[0].strip()
        parts = [p.strip() for p in header.split("|") if p.strip()]
        # Posts that skip the convention can't be read reliably.
        if len(parts) < 2:
            continue
        jobs.append(
            Job(
                source=NAME,
                url=f"https://news.ycombinator.com/item?id={comment['id']}",
                company=parts[0],
                title=" | ".join(parts[1:]),
                location=" | ".join(parts[1:]),
                remote=bool(REMOTE.search(header)),
                description=text,
                posted_at=comment.get("created_at"),
            )
        )
    return jobs


def fetch(http, companies: dict) -> list[Job]:
    hits = http.get_json(
        SEARCH_URL,
        params={
            "query": '"Ask HN: Who is hiring"',
            "tags": "story,author_whoishiring",
            "hitsPerPage": 5,
        },
    ).get("hits", [])
    threads = [h for h in hits if "who is hiring" in (h.get("title") or "").lower()]
    if not threads:
        return []
    return parse_thread(http.get_json(ITEM_URL.format(threads[0]["objectID"])))
