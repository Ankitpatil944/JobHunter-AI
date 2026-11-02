"""Decide what, if anything, goes in a form field. Pure logic, with no browser."""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

SUPPORTED_HOSTS = {
    "job-boards.greenhouse.io": "greenhouse",
    "boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
}

# Personal, legal or company-specific: left for the person unless they wrote an answer in `answers`.
SENSITIVE = re.compile(
    r"gender|\bsex\b|sexual|race\b|racial|ethnic|hispanic|latino|veteran|disab|pronoun|religio|caste|"
    r"date of birth|\bdob\b|\bage\b|marital|criminal|convict|\bsat\b|\bact\b|\bgpa\b|"
    r"consent|acknowledg|agree|privacy|terms|certif|attest|"
    r"previously (worked|employed|applied)|employment agreement|non-?compete|relative|related to|"
    r"cover letter",
    re.I,
)

# First match wins, so more specific patterns come first.
FIELD_RULES = [
    (r"first name|given name", "name.first"),
    (r"last name|surname|family name", "name.last"),
    (r"^(full |legal |your )?name\b", "name.full"),
    (r"e-?mail", "email"),
    (r"phone|mobile|contact number", "phone"),
    (r"linkedin", "links.linkedin"),
    (r"github", "links.github"),
    (r"portfolio|website", "links.portfolio"),
    # Before location rules, as these questions often mention a country or location.
    (r"(eligible|authori[sz]ed|right|legally).{0,40}work.{0,40}india", "authorization.authorized_in_india"),
    (r"(require|need).{0,50}sponsor", "derived.sponsorship"),
    (r"located in india", "derived.located_in_india"),
    (r"country", "location.country"),
    (r"\bcity\b|^location\b|current location", "location.city"),
    (r"(current|previous|most recent).{0,20}(employer|company)|^(org|company)\b", "work.current_company"),
    (r"(current|previous|most recent).{0,20}(job )?title", "work.current_title"),
    (r"notice period", "work.notice_period_days"),
    (r"expected.{0,20}(salary|ctc|compensation)", "derived.expected_salary"),
    (r"years.{0,20}experience", "work.years_experience"),
    (r"relocat", "authorization.willing_to_relocate"),
    (r"\bschool\b|university|college", "education.school"),
    (r"\bdegree\b", "education.degree"),
]
FIELD_RULES = [(re.compile(pattern, re.I), key) for pattern, key in FIELD_RULES]
MAX_PLAIN_LABEL = 70
YES_NO_KEYS = ("authorization.", "derived.located", "derived.sponsorship", "location.country")


@dataclass
class Decision:
    status: str  # "fill", "sensitive", "no_answer" (recognized, blank in profile) or "unknown"
    value: str = ""


def detect_system(url: str) -> str | None:
    return SUPPORTED_HOSTS.get(urlsplit(url or "").netloc.lower())


def _lookup(profile: dict, key: str) -> str:
    value = profile
    for part in key.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return "" if value is None else str(value).strip()


def _derived(key: str, profile: dict, label: str, india_job: bool) -> str:
    if key == "name.full":
        full = " ".join(p for p in (_lookup(profile, "name.first"), _lookup(profile, "name.last")) if p)
        return full
    if key == "derived.located_in_india":
        country = _lookup(profile, "location.country")
        return ("Yes" if country.lower() == "india" else "No") if country else ""
    if key == "derived.sponsorship":
        india = india_job or "india" in label.lower()
        return _lookup(profile, f"authorization.needs_sponsorship_{'india' if india else 'abroad'}")
    if key == "derived.expected_salary":
        return _lookup(profile, f"work.expected_salary_{'inr' if india_job else 'usd'}")
    return _lookup(profile, key)


def decide(label: str, profile: dict, india_job: bool = True) -> Decision:
    label = " ".join((label or "").split())
    if not label:
        return Decision("unknown")
    # A person's own written answer can cover anything, including sensitive questions.
    for item in profile.get("answers") or []:
        if item.get("match") and str(item["match"]).lower() in label.lower() and item.get("answer"):
            return Decision("fill", str(item["answer"]))
    if SENSITIVE.search(label):
        return Decision("sensitive")
    for pattern, key in FIELD_RULES:
        if pattern.search(label):
            # A long question can mention "school" or "company" without asking for it.
            if len(label) > MAX_PLAIN_LABEL and not key.startswith(YES_NO_KEYS):
                return Decision("unknown")
            value = _derived(key, profile, label, india_job)
            return Decision("fill", value) if value else Decision("no_answer")
    return Decision("unknown")
