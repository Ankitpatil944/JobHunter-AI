"""Free, rule-based filtering: role match, market tags and eligibility.

Eligibility is deliberately cautious:
  open        clearly open to candidates in India
  check       unclear, so a person or /triage must read the posting
  restricted  limited to somewhere else
"""
import re
from datetime import datetime, timedelta, timezone

INDIA = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|pune|mumbai|delhi|ncr|gurgaon|gurugram|noida|"
    r"chennai|kolkata|ahmedabad|kochi|coimbatore|jaipur|indore)\b",
    re.I,
)
WORLDWIDE = re.compile(r"\b(worldwide|anywhere|global|globally)\b", re.I)
REGION = re.compile(r"\b(apac|asia|asia[- ]pacific|emea and apac)\b", re.I)
GENERIC_REMOTE = re.compile(r"[^a-z]*(remote|fully remote|100% remote|work from home)?[^a-z]*", re.I)

COUNTRY_LOCK = re.compile(
    r"(must (be|reside|live)[^.\n]{0,40}\b(in|within)\b[^.\n]{0,30}\b(us|u\.s\.|usa|united states|uk|canada|europe|eu)\b"
    r"|authori[sz]ed to work in the (us|u\.s\.|usa|united states|uk|eu|european union)"
    r"|(us|u\.s\.) (citizens?|residents?) only"
    r"|security clearance)",
    re.I,
)
NO_SPONSOR = re.compile(
    r"(no|not|without|unable to|cannot|can't|can not|won't|will not|do not|does not|don't|doesn't)"
    r"[^.\n]{0,50}\b(visa|sponsor|sponsorship)\b"
    r"|\b(visa|sponsorship)\b[^.\n]{0,30}\b(not available|unavailable|not provided|not offered|not possible)\b"
    # Application questions like "Will you require visa sponsorship?" aren't offers.
    r"|\b(require|requires|need|needs)\b[^.\n]{0,30}\bsponsorship\b",
    re.I,
)
TITLE_LOCK = re.compile(
    r"(remote eligible in|\blatam\b|latin america|\bemea\b|"
    r"\b(us|usa|uk|eu|canada|europe) only\b|"
    r"remote\s*[-–(,/:]?\s*\(?(us|usa|u\.s\.|uk|canada|europe|eu|germany|brazil|mexico|poland|spain|france|australia)\b)",
    re.I,
)
# "5+ years of experience", "3-5 years' experience", "minimum 6 years of relevant experience".
REQUIRED_YEARS = re.compile(
    r"\b(\d{1,2})\s*(?:\+|plus|or more|(?:-|–|to)\s*\d{1,2}\+?)?\s*years?\b[^.\n]{0,40}\bexperience\b",
    re.I,
)
# These boards only list open roles, so an old post date doesn't mean the job has closed.
LIVE_BOARDS = {"greenhouse", "ashby", "lever", "workday"}
SPONSOR = re.compile(
    r"(visa sponsorship|sponsor(s|ing)? (a |your |work )?(visa|visas|work permit)|"
    r"relocation and visa|visa and relocation|visa support|work permit support)",
    re.I,
)


def _phrases(items: list[str]) -> re.Pattern | None:
    if not items:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(i) for i in items) + r")\b", re.I)


class Rules:
    def __init__(self, search: dict):
        self.roles = {name: _phrases(words) for name, words in (search.get("roles") or {}).items()}
        self.exclude = _phrases(search.get("exclude_titles") or [])
        self.always_allow = _phrases(search.get("always_allow") or [])
        self.max_required_years = search.get("max_required_years")
        self.max_age_days = search.get("max_age_days", 30)


def match_role(title: str, rules: Rules) -> str | None:
    for name, pattern in rules.roles.items():
        if pattern and pattern.search(title):
            return name
    return None


def _excluded(title: str, rules: Rules) -> bool:
    checked = rules.always_allow.sub(" ", title) if rules.always_allow else title
    return bool(rules.exclude and rules.exclude.search(checked))


def title_matches(title: str, rules: Rules) -> bool:
    return bool(match_role(title, rules)) and not _excluded(title, rules)


def required_years(description: str) -> int | None:
    """The lowest experience requirement stated, since higher ones are often only preferred."""
    years = [int(m) for m in REQUIRED_YEARS.findall(description or "")]
    return min(years) if years else None


def offers_visa(description: str) -> bool:
    """True only on an explicit offer. A refusal anywhere in the text wins."""
    return bool(SPONSOR.search(description or "")) and not NO_SPONSOR.search(description or "")


def classify_market(location: str, remote: bool, description: str = "", title: str = "") -> tuple[list[str], str]:
    """Return (market tags, eligibility) for a job."""
    location = location or ""
    description = description or ""
    locked = bool(COUNTRY_LOCK.search(description))

    if INDIA.search(location) or INDIA.search(title):
        return (["india_remote"] if remote else ["india_onsite"]), "open"

    if TITLE_LOCK.search(title):
        return (["visa_sponsor"], "check") if offers_visa(description) else ([], "restricted")

    if not remote:
        if offers_visa(description):
            return ["visa_sponsor"], "check"
        return [], "restricted"

    if WORLDWIDE.search(location):
        return ["global_remote"], ("check" if locked else "open")
    if REGION.search(location) or GENERIC_REMOTE.fullmatch(location):
        return ["global_remote"], "check"

    # Remote, but tied to somewhere else. It may still offer a visa route.
    if offers_visa(description):
        return ["visa_sponsor"], "check"
    return [], "restricted"


def too_old(posted_at: str | None, max_age_days: int, today: datetime | None = None) -> bool:
    if not posted_at:
        return False
    try:
        posted = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=timezone.utc)
    return (today or datetime.now(timezone.utc)) - posted > timedelta(days=max_age_days)


def evaluate(title: str, location: str, remote: bool, description: str, posted_at: str | None, rules: Rules,
             source: str = "") -> dict:
    markets, eligibility = classify_market(location, remote, description, title)
    role = match_role(title, rules)
    reason = None
    years = required_years(description)
    if _excluded(title, rules):
        reason = "excluded title"
    elif not role:
        reason = "no role match"
    elif source not in LIVE_BOARDS and too_old(posted_at, rules.max_age_days):
        reason = "too old"
    elif eligibility == "restricted":
        reason = "not open to India"
    elif rules.max_required_years is not None and years is not None and years > rules.max_required_years:
        reason = "too much experience required"
    return {
        "relevant": int(reason is None),
        "role": role,
        "markets": ",".join(markets),
        "eligibility": eligibility,
        "filter_reason": reason,
    }


def apply_filters(conn, rules: Rules) -> int:
    """Re-evaluate every job, so config changes apply to jobs already stored."""
    rows = conn.execute("SELECT id, source, title, location, remote, description, posted_at FROM jobs").fetchall()
    relevant = 0
    for row in rows:
        result = evaluate(row["title"], row["location"], bool(row["remote"]), row["description"], row["posted_at"],
                          rules, row["source"])
        relevant += result["relevant"]
        conn.execute(
            """UPDATE jobs SET relevant = :relevant, role = :role, markets = :markets,
                   eligibility = :eligibility, filter_reason = :filter_reason WHERE id = :id""",
            {**result, "id": row["id"]},
        )
    return relevant
