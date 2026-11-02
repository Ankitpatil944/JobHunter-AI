"""Parser tests using small samples written to match the formats each source returned."""
import sqlite3

import httpx

from jobhunter import db
from jobhunter.http import Http
from jobhunter.models import Job, normalize_url
from jobhunter.sources import (
    arbeitnow, ashby, greenhouse, hackernews, himalayas, jobicy, lever, remoteok, remotive, weworkremotely, workday,
)


def test_remoteok_skips_legal_notice():
    jobs = remoteok.parse([
        {"last_updated": 1, "legal": "API Terms of Service"},
        {"position": "Backend Engineer", "company": "Acme", "url": "https://remoteOK.com/x",
         "location": "", "description": "<p>Hi</p>", "date": "2026-11-01T08:00:12+00:00"},
    ])
    assert len(jobs) == 1
    assert jobs[0].title == "Backend Engineer" and jobs[0].remote and jobs[0].description == "Hi"


def test_remotive():
    job = remotive.parse({"jobs": [{
        "url": "https://remotive.com/j/1", "title": "SDE", "company_name": "Acme",
        "candidate_required_location": "Worldwide", "description": "<b>x</b>",
        "publication_date": "2026-10-29T18:22:41",
    }]})[0]
    assert (job.company, job.location, job.description) == ("Acme", "Worldwide", "x")


def test_himalayas_joins_locations_and_converts_dates():
    job = himalayas.parse({"jobs": [{
        "title": "SDE", "companyName": "Acme", "guid": "https://himalayas.app/x",
        "applicationLink": "https://himalayas.app/x", "locationRestrictions": ["India", "Nepal"],
        "description": "<p>d</p>", "pubDate": 1793646205,
    }]})[0]
    assert job.location == "India, Nepal"
    assert job.posted_at.startswith("2026-")


def test_himalayas_follows_cursor():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "cursor=next" in str(request.url):
            return httpx.Response(200, json={"jobs": [], "nextCursor": None})
        return httpx.Response(200, json={"jobs": [], "nextCursor": "next"})

    http = Http(delay=0, transport=httpx.MockTransport(handler))
    assert himalayas.fetch(http, {}) == []
    assert len(calls) == 2


def test_jobicy():
    job = jobicy.parse({"jobs": [{
        "url": "https://jobicy.com/1", "jobTitle": "SDE", "companyName": "Reddit", "jobGeo": "USA",
        "jobDescription": "<p>d</p>", "pubDate": "2026-11-02T16:01:08+00:00",
    }]})[0]
    assert (job.company, job.location, job.remote) == ("Reddit", "USA", True)


def test_arbeitnow_reads_remote_flag():
    job = arbeitnow.parse({"data": [{
        "url": "https://arbeitnow.com/1", "title": "SDE", "company_name": "Acme", "location": "Bonn",
        "remote": False, "description": "<p>d</p>", "created_at": 1793646037,
    }]})[0]
    assert job.remote is False and job.location == "Bonn"


def test_weworkremotely_splits_company_and_title():
    xml = """<?xml version="1.0"?><rss version="2.0"><channel><item>
      <title>Acme Corp: Senior: Backend Engineer</title>
      <region>Anywhere in the World</region>
      <description>&lt;p&gt;Text&lt;/p&gt;</description>
      <pubDate>Mon, 02 Nov 2026 10:00:00 +0000</pubDate>
      <link>https://weworkremotely.com/remote-jobs/acme</link>
    </item></channel></rss>"""
    job = weworkremotely.parse(xml)[0]
    assert job.company == "Acme Corp"
    assert job.title == "Senior: Backend Engineer"
    assert job.location == "Anywhere in the World"
    assert job.description == "Text" and job.posted_at.startswith("2026-11-02")


def test_hackernews_reads_header_and_skips_freeform():
    jobs = hackernews.parse_thread({"children": [
        {"id": 1, "text": "<p>Acme | Backend Engineer | REMOTE (Worldwide)<p>More", "created_at": "2026-11-02T16:01:37Z"},
        {"id": 2, "text": "We are hiring lots of people, email us."},
        {"id": 3, "text": None},
    ]})
    assert len(jobs) == 1
    assert jobs[0].company == "Acme" and jobs[0].remote
    assert jobs[0].url == "https://news.ycombinator.com/item?id=1"


def test_greenhouse_unescapes_content():
    job = greenhouse.parse({"jobs": [{
        "absolute_url": "https://stripe.com/jobs/search?gh_jid=1", "title": "SDE", "company_name": "Stripe",
        "location": {"name": "Remote - India"}, "content": "&lt;p&gt;About&lt;/p&gt;",
        "first_published": "2026-09-03T13:30:34-04:00",
    }]}, "stripe")[0]
    assert job.remote and job.description == "About"


def test_greenhouse_bad_slug_only_warns():
    http = Http(delay=0, transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    assert greenhouse.fetch(http, {"greenhouse": ["nope"]}) == []
    assert "nope" in http.warnings[0]


def test_ashby_combines_locations_and_skips_unlisted():
    jobs = ashby.parse({"jobs": [
        {"title": " SDE ", "jobUrl": "https://jobs.ashbyhq.com/a/1", "location": "New York",
         "secondaryLocations": [{"location": "Remote (Canada)"}], "isRemote": True,
         "descriptionPlain": "d", "publishedAt": "2026-04-07T17:12:35+00:00", "isListed": True},
        {"title": "Hidden", "jobUrl": "https://jobs.ashbyhq.com/a/2", "isListed": False},
    ]}, "ramp")
    assert len(jobs) == 1
    assert jobs[0].title == "SDE" and jobs[0].location == "New York, Remote (Canada)"


def test_lever_combines_description_and_converts_milliseconds():
    job = lever.parse([{
        "text": " SDE ", "hostedUrl": "https://jobs.lever.co/cred/1", "applyUrl": "https://jobs.lever.co/cred/1/apply",
        "categories": {"location": "hyderabad", "allLocations": ["hyderabad", "Bangalore"]},
        "workplaceType": "onsite", "createdAt": 1793646205000, "descriptionPlain": "About",
        "lists": [{"text": "Requirements", "content": "<li>Python</li>"}], "additionalPlain": "Benefits",
    }], "cred")[0]
    assert (job.title, job.location, job.remote) == ("SDE", "hyderabad, Bangalore", False)
    assert job.posted_at.startswith("2026-") and job.apply_url.endswith("/apply")
    assert all(text in job.description for text in ("About", "Requirements", "Python", "Benefits"))


def test_workday_detail_includes_country():
    job = workday.parse_detail({"jobPostingInfo": {
        "title": "SDE", "externalUrl": "https://x.wd1.myworkdayjobs.com/s/job/1", "location": "Pune",
        "additionalLocations": ["Mumbai"], "country": {"descriptor": "India"}, "jobDescription": "<p>d</p>",
        "startDate": "2026-10-30", "remoteType": "Hybrid",
    }}, "Mastercard")
    assert (job.company, job.location, job.remote) == ("Mastercard", "Pune, Mumbai, India", False)
    assert workday.parse_detail({"jobPostingInfo": {}}, "X") is None


def test_workday_fetches_details_only_for_matching_titles(monkeypatch):
    monkeypatch.setattr(workday, "QUERIES", ["software engineer"])
    monkeypatch.setattr(workday, "load_yaml", lambda name: {
        "roles": {"software": ["software engineer"]}, "exclude_titles": ["senior"],
    })
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, json={"jobPostings": [
                {"title": "Software Engineer", "externalPath": "/job/a"},
                {"title": "Senior Software Engineer", "externalPath": "/job/b"},
                {"title": "Technician", "externalPath": "/job/c"},
            ]})
        return httpx.Response(200, json={"jobPostingInfo": {"title": "Software Engineer", "externalUrl": "https://x/a"}})

    http = Http(delay=0, transport=httpx.MockTransport(handler))
    jobs = workday.fetch(http, {"workday": [{"name": "Acme", "tenant": "acme", "dc": "wd1", "site": "S"}]})
    assert [j.company for j in jobs] == ["Acme"]
    assert [path for method, path in calls if method == "GET"] == ["/wday/cxs/acme/S/job/a"]


def test_greenhouse_and_ashby_give_form_addresses():
    gh = greenhouse.parse({"jobs": [{"absolute_url": "https://stripe.com/x", "id": 7, "title": "SDE"}]}, "stripe")[0]
    assert gh.apply_url == "https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=7"
    ash = ashby.parse({"jobs": [{"title": "SDE", "jobUrl": "https://jobs.ashbyhq.com/a/1"}]}, "a")[0]
    assert ash.apply_url == "https://jobs.ashbyhq.com/a/1/application"


def test_old_database_gets_apply_url_column(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, url TEXT, relevant INTEGER, eligibility TEXT)")
    old.commit()
    old.close()
    conn = db.connect(path)
    assert "apply_url" in {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}


def test_refetch_fills_in_apply_url():
    conn = db.connect(":memory:")
    db.upsert_job(conn, make())
    job = make()
    job.apply_url = "https://job-boards.greenhouse.io/embed/job_app?for=a&token=1"
    db.upsert_job(conn, job)
    assert conn.execute("SELECT apply_url FROM jobs").fetchone()["apply_url"] == job.apply_url


def test_application_status_keeps_earlier_values():
    conn = db.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = OFF")
    db.set_application(conn, 1, "prefilled", resume_path="a.pdf")
    db.set_application(conn, 1, "applied", applied_at="2026-11-03", follow_up_on="2026-11-10")
    row = conn.execute("SELECT * FROM applications").fetchone()
    assert (row["status"], row["resume_path"], row["follow_up_on"]) == ("applied", "a.pdf", "2026-11-10")


def test_normalize_url_keeps_job_ids_and_drops_tracking():
    assert normalize_url("https://STRIPE.com/jobs/?gh_jid=1&utm_source=x") == "https://stripe.com/jobs?gh_jid=1"
    assert normalize_url("https://stripe.com/jobs?gh_jid=1") != normalize_url("https://stripe.com/jobs?gh_jid=2")


def make(source="remoteok", url="https://a.com/1", company="Acme Inc", title="SDE", location="India"):
    return Job(source=source, url=url, company=company, title=title, location=location)


def test_same_url_is_not_duplicated():
    conn = db.connect(":memory:")
    assert db.upsert_job(conn, make()) is True
    assert db.upsert_job(conn, make(url="https://a.com/1?utm_source=x")) is False
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_same_job_on_two_boards_is_merged():
    conn = db.connect(":memory:")
    db.upsert_job(conn, make())
    assert db.upsert_job(conn, make(source="remotive", url="https://b.com/9", company="ACME, Ltd.")) is False
    row = conn.execute("SELECT source, also_on FROM jobs").fetchone()
    assert (row["source"], row["also_on"]) == ("remoteok", "remotive")


def test_same_role_in_other_city_is_kept():
    conn = db.connect(":memory:")
    db.upsert_job(conn, make())
    assert db.upsert_job(conn, make(url="https://a.com/2", location="Pune")) is True
