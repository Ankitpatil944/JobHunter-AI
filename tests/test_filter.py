from datetime import datetime, timezone

import pytest

from jobhunter.filter import Rules, classify_market, evaluate, match_role, offers_visa, required_years, too_old

RULES = Rules({
    "roles": {
        "ml_eng": ["machine learning"],
        "ai": ["ai engineer"],
        "backend": ["backend", "back-end"],
        "software": ["software engineer", "sde", "member of technical staff"],
    },
    "exclude_titles": ["manager", "sales", "vp", "staff", "senior"],
    "always_allow": ["member of technical staff"],
    "max_required_years": 4,
    "max_age_days": 30,
})


@pytest.mark.parametrize("location,remote,expected", [
    ("Bengaluru, India", False, (["india_onsite"], "open")),
    ("Remote - India", True, (["india_remote"], "open")),
    ("USA, India", True, (["india_remote"], "open")),
    ("Worldwide", True, (["global_remote"], "open")),
    ("Anywhere in the World", True, (["global_remote"], "open")),
    ("APAC", True, (["global_remote"], "check")),
    ("", True, (["global_remote"], "check")),
    ("Remote", True, (["global_remote"], "check")),
    ("Remote (US)", True, ([], "restricted")),
    ("USA", True, ([], "restricted")),
    ("San Francisco, CA", False, ([], "restricted")),
])
def test_classify_market(location, remote, expected):
    assert classify_market(location, remote) == expected


def test_indiana_is_not_india():
    assert classify_market("Indianapolis, Indiana", False) == ([], "restricted")
    assert classify_market("Remote, Indiana", True) == ([], "restricted")


def test_worldwide_with_country_lock_needs_checking():
    text = "Applicants must be authorized to work in the United States."
    assert classify_market("Worldwide", True, text) == (["global_remote"], "check")


@pytest.mark.parametrize("text,expected", [
    ("We offer visa sponsorship and relocation.", True),
    ("We can sponsor your visa.", True),
    ("We do not offer visa sponsorship.", False),
    ("Unable to provide visa sponsorship for this role.", False),
    ("Great benefits and a friendly team.", False),
    ("", False),
    ("You must be a student. Visa sponsorship is not available.", False),
    ("Will you now or in the future require visa sponsorship?", False),
    ("Highly skilled migrant visa sponsorship and relocation support.", True),
    ("Visa sponsorship: We do sponsor visas! However, we aren't able to sponsor every role.", True),
])
def test_offers_visa_needs_explicit_offer(text, expected):
    assert offers_visa(text) is expected


def test_visa_tag_only_with_explicit_offer():
    assert classify_market("Berlin", False, "Visa sponsorship provided.") == (["visa_sponsor"], "check")
    assert classify_market("Berlin", False, "No visa sponsorship.") == ([], "restricted")


@pytest.mark.parametrize("title,expected", [
    ("Senior Backend Engineer", "backend"),
    ("Machine Learning Engineer", "ml_eng"),
    ("SDE II", "software"),
    ("Aide to the Director", None),
    ("Sales Consultant", None),
])
def test_match_role_uses_whole_words(title, expected):
    assert match_role(title, RULES) == expected


def test_first_role_wins():
    assert match_role("Machine Learning Software Engineer", RULES) == "ml_eng"


def test_too_old():
    today = datetime(2026, 11, 3, tzinfo=timezone.utc)
    assert too_old("2026-09-01T00:00:00Z", 30, today)
    assert not too_old("2026-10-20T00:00:00+00:00", 30, today)
    assert not too_old("2026-10-20T00:00:00", 30, today)
    assert not too_old(None, 30, today)
    assert not too_old("not a date", 30, today)


@pytest.mark.parametrize("title", [
    "Principal Software Engineer (Remote Eligible in Bulgaria)",
    "Senior Software Engineer LATAM",
    "Backend Engineer - Remote US",
    "Backend Engineer, Remote (Canada)",
    "SDE, EU only",
])
def test_title_restrictions_override_worldwide(title):
    assert classify_market("Anywhere in the World", True, "", title) == ([], "restricted")


def test_india_in_title_counts():
    assert classify_market("", True, "", "Backend Engineer - India") == (["india_remote"], "open")


def test_remote_in_plain_title_is_not_a_restriction():
    assert classify_market("Worldwide", True, "", "Senior Full-stack Engineer - Remote") == (["global_remote"], "open")


def test_age_limit_skips_live_company_boards():
    old = "2020-01-01T00:00:00+00:00"
    assert evaluate("Backend Engineer", "India", False, "", old, RULES, "greenhouse")["filter_reason"] is None
    assert evaluate("Backend Engineer", "India", False, "", old, RULES, "remoteok")["filter_reason"] == "too old"


@pytest.mark.parametrize("text,expected", [
    ("5+ years of experience in Python", 5),
    ("3-5 years' experience with SQL", 3),
    ("3 to 5 years of relevant experience", 3),
    ("Minimum 6 years of backend experience", 6),
    ("2+ years of experience required. 8+ years of experience preferred.", 2),
    ("We were founded 20 years ago.", None),
    ("", None),
])
def test_required_years(text, expected):
    assert required_years(text) == expected


def test_experience_limit():
    def reason(text):
        return evaluate("Backend Engineer", "India", False, text, None, RULES)["filter_reason"]

    assert reason("7+ years of experience") == "too much experience required"
    assert reason("4 years of experience") is None
    assert reason("No requirement stated") is None


def test_seniority_titles_and_allowed_phrase():
    def reason(title):
        return evaluate(title, "India", False, "", None, RULES)["filter_reason"]

    assert reason("Staff Software Engineer") == "excluded title"
    assert reason("Senior Backend Engineer") == "excluded title"
    assert reason("Member of Technical Staff") is None


def test_evaluate_reasons():
    def reason(title, location="India", remote=False):
        return evaluate(title, location, remote, "", None, RULES)["filter_reason"]

    assert reason("Backend Engineer") is None
    assert reason("Backend Engineering Manager") == "excluded title"
    assert reason("Barista") == "no role match"
    assert reason("Backend Engineer", "Austin, TX") == "not open to India"
