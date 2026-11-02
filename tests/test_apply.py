import os
import re
from pathlib import Path

import pytest

from jobhunter import cli, db
from jobhunter.apply import filler
from jobhunter.apply.fields import decide, detect_system
from jobhunter.models import Job

PROFILE = {
    "name": {"first": "Test", "last": "Person"},
    "email": "test@example.com",
    "phone": "+91 9000000000",
    "location": {"city": "Bengaluru", "country": "India"},
    "links": {"linkedin": "https://linkedin.com/in/test", "github": ""},
    "work": {"current_company": "", "expected_salary_inr": "1000000", "expected_salary_usd": "50000"},
    "authorization": {"authorized_in_india": "Yes", "needs_sponsorship_india": "No", "needs_sponsorship_abroad": "Yes"},
    "education": {"school": "Test College"},
}


@pytest.mark.parametrize("label,value", [
    ("First Name*", "Test"),
    ("Last Name", "Person"),
    ("Name", "Test Person"),
    ("Full name", "Test Person"),
    ("Email", "test@example.com"),
    ("Phone number", "+91 9000000000"),
    ("LinkedIn Profile, Github, Personal Website, or Portfolio", "https://linkedin.com/in/test"),
    ("Country", "India"),
    ("What is your current country of residence?", "India"),
    ("Are you located in India?", "Yes"),
    ("Location (City)", "Bengaluru"),
    ("Are you currently eligible to work in India?", "Yes"),
    ("School", "Test College"),
])
def test_fills_known_fields(label, value):
    decision = decide(label, PROFILE)
    assert (decision.status, decision.value) == ("fill", value)


@pytest.mark.parametrize("label", [
    "Gender", "Are you Hispanic/Latino?", "Veteran Status", "Disability status", "Pronouns",
    "Please share your SAT or ACT score", "GPA", "I agree to the privacy policy",
    "Have you previously worked at or consulted for GitLab?",
    "Are you subject to any employment agreements and/or post-employment restrictions?",
    "Cover letter",
])
def test_never_answers_sensitive_questions(label):
    assert decide(label, PROFILE).status == "sensitive"


def test_blank_profile_value_is_not_guessed():
    assert decide("Who is your current or previous employer?", PROFILE).status == "no_answer"
    assert decide("GitHub URL", PROFILE).status == "no_answer"


def test_unrecognized_question_is_left_alone():
    assert decide("Why do you want to work here?", PROFILE).status == "unknown"
    assert decide("", PROFILE).status == "unknown"


def test_sponsorship_depends_on_the_job():
    label = "Will you now or in the future require sponsorship for a visa?"
    assert decide(label, PROFILE, india_job=True).value == "No"
    assert decide(label, PROFILE, india_job=False).value == "Yes"
    assert decide("Do you require visa sponsorship to work in India?", PROFILE, india_job=False).value == "No"


def test_long_question_mentioning_a_keyword_is_left_alone():
    label = ("We are always aiming to keep our school list inclusive of all institutions. "
             "If you do not see your University listed, let us know your school.")
    assert decide(label, PROFILE).status == "unknown"
    long_sponsorship = "Will you now or in the future require sponsorship for a visa to remain in your current location?"
    assert decide(long_sponsorship, PROFILE, india_job=True).value == "No"


def test_apply_command_uses_a_named_copy_and_records_it(tmp_path, monkeypatch):
    conn = db.connect(":memory:")
    db.upsert_job(conn, Job(source="greenhouse", url="https://a.com/1", company="Acme", title="SDE", location="Pune",
                            apply_url="https://job-boards.greenhouse.io/embed/job_app?for=a&token=1"))
    conn.execute("UPDATE jobs SET markets = 'india_onsite'")
    folder = tmp_path / "1"
    folder.mkdir()
    (folder / "resume.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "profile.yaml").write_text("x: 1", encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli.db, "connect", lambda: conn)
    monkeypatch.setattr(cli, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cli, "load_yaml", lambda name: PROFILE)
    monkeypatch.setattr(cli.tailor, "TAILORED_DIR", tmp_path)
    monkeypatch.setattr(filler, "run_browser", lambda *args: calls.append(args))

    assert cli.main(["apply", "1"]) == 0
    url, _, pdf, india_job, supported, _ = calls[0]
    assert pdf.name == "Test_Person_Resume.pdf" and pdf.exists()
    assert url.startswith("https://job-boards") and india_job and supported
    assert conn.execute("SELECT status FROM applications").fetchone()["status"] == "prefilled"

    assert cli.main(["mark", "1", "applied"]) == 0
    row = conn.execute("SELECT status, applied_at, follow_up_on FROM applications").fetchone()
    assert row["status"] == "applied" and row["applied_at"] and row["follow_up_on"]


def test_apply_refuses_without_a_resume(tmp_path, monkeypatch):
    conn = db.connect(":memory:")
    db.upsert_job(conn, Job(source="x", url="https://a.com/1", company="Acme", title="SDE"))
    (tmp_path / "profile.yaml").write_text("x: 1", encoding="utf-8")
    monkeypatch.setattr(cli.db, "connect", lambda: conn)
    monkeypatch.setattr(cli, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cli, "load_yaml", lambda name: PROFILE)
    monkeypatch.setattr(cli.tailor, "TAILORED_DIR", tmp_path)
    assert cli.main(["apply", "1"]) == 1


@pytest.mark.parametrize("label", [
    "Do you need sponsorship to work in this country?",
    "Will you require sponsorship in your current location?",
])
def test_sponsorship_questions_never_get_a_location(label):
    assert decide(label, PROFILE).value == "No"


def test_written_answers_win():
    profile = {**PROFILE, "answers": [{"match": "gender", "answer": "Prefer not to say"}]}
    assert decide("Gender", profile).value == "Prefer not to say"


@pytest.mark.parametrize("url,system", [
    ("https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=1", "greenhouse"),
    ("https://jobs.lever.co/meesho/abc/apply", "lever"),
    ("https://jobs.ashbyhq.com/sarvam/abc/application", "ashby"),
    ("https://nvidia.wd5.myworkdayjobs.com/x", None),
    ("", None),
])
def test_detect_system(url, system):
    assert detect_system(url) == system


def test_source_has_no_way_to_submit():
    """Only the dropdown option may be clicked, and Enter may never be pressed."""
    source = Path(filler.__file__).read_text(encoding="utf-8")
    code = re.sub(r'""".*?"""', "", source, flags=re.S)
    code = "\n".join(line.split("#")[0] for line in code.splitlines())
    assert "Enter" not in code
    assert ".submit" not in code and "requestSubmit" not in code
    assert re.findall(r"([\w\[\]]+)\.click\(", code) == ["element", "chosen[0]"]
    assert "button" not in code.replace('"button"', "")


FORM = """<!doctype html><title>t</title>
<form id="f" action="javascript:void(0)" onsubmit="window.submitted = (window.submitted || 0) + 1; return false">
  <label for="first_name">First Name*</label><input id="first_name" aria-required="true">
  <label for="email">Email</label><input id="email" type="email" required>
  <label for="employer">Who is your current or previous employer?*</label><input id="employer" aria-required="true">
  <label for="why">Why us?*</label><textarea id="why" required></textarea>
  <label for="fun">Favorite color</label><input id="fun">
  <label for="gender">Gender</label><select id="gender" required><option></option><option>Male</option></select>
  <label for="c">I agree to the terms</label><input id="c" name="c" type="checkbox" required>
  <label for="country">Country</label>
  <input id="country" role="combobox" aria-required="true"
         oninput="document.getElementById('list').style.display = this.value ? 'block' : 'none'">
  <div id="list" style="display:none">
    <div role="option" onclick="document.getElementById('country').dataset.chosen = this.innerText">India</div>
    <div role="option">Indonesia</div>
  </div>
  <ul style="display:none"><li role="option" onclick="window.wrongList = true">India</li></ul>
  <label for="school">School</label><input id="school" role="combobox">
  <fieldset>
    <legend>Are you willing to travel?</legend>
    <label><input type="radio" name="travel" required>Yes</label>
    <label><input type="radio" name="travel" required>No</label>
  </fieldset>
  <label for="cover_letter">Attach</label><input id="cover_letter" type="file">
  <label for="resume">Attach</label><input id="resume" type="file">
  <button type="submit" id="send">Submit application</button>
</form>"""


@pytest.fixture
def form_page():
    if not filler.BROWSERS_DIR.exists():
        pytest.skip("Chromium not installed")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(filler.BROWSERS_DIR)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(FORM)
        yield page
        browser.close()


@pytest.fixture
def sample_pdf(tmp_path):
    path = tmp_path / "resume.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    return path


def test_fill_page_never_submits(form_page, sample_pdf):
    filler.fill_page(form_page, PROFILE, sample_pdf)
    assert form_page.evaluate("window.submitted || 0") == 0


def test_fill_page_fills_known_and_flags_the_rest(form_page, sample_pdf):
    report = filler.fill_page(form_page, PROFILE, sample_pdf)
    assert form_page.input_value("#first_name") == "Test"
    assert form_page.input_value("#email") == "test@example.com"
    assert form_page.input_value("#employer") == ""
    assert form_page.input_value("#why") == ""
    assert form_page.input_value("#gender") == ""
    assert not form_page.is_checked("#c")
    for label in ("Why us?", "Gender", "I agree to the terms", "Who is your current or previous employer?"):
        assert label in report.needs_you
    assert "outline" in form_page.get_attribute("#why", "style")
    assert "Favorite color" in report.optional_blank


def test_dropdown_needs_an_exact_match(form_page, sample_pdf):
    report = filler.fill_page(form_page, PROFILE, sample_pdf)
    assert form_page.get_attribute("#country", "data-chosen") == "India"
    assert ("Country", "India") in report.filled
    # "Test College" has no option, so nothing is left typed in.
    assert form_page.input_value("#school") == ""


def _options_page(form_page, *options):
    items = "".join(f'<div role="option" onclick="window.picked = this.innerText">{o}</div>' for o in options)
    form_page.set_content(f'<input id="q" role="combobox"><div>{items}</div>')
    return form_page.query_selector("#q")


@pytest.mark.parametrize("options,value,picked", [
    (["Yes, I am eligible", "No, I am not"], "Yes", "Yes, I am eligible"),
    (["Yes, I am eligible", "Yes, with sponsorship"], "Yes", None),
    (["Yes", "Yes, with sponsorship"], "Yes", "Yes"),
    (["India +91", "British Indian Ocean Territory +246"], "India", "India +91"),
    (["Indiana", "Indonesia"], "India", None),
])
def test_dropdown_only_picks_a_clear_match(form_page, options, value, picked):
    box = _options_page(form_page, *options)
    assert filler._pick_option(form_page, box, value) is (picked is not None)
    assert form_page.evaluate("window.picked || null") == picked


def test_dropdown_ignores_hidden_lists(form_page, sample_pdf):
    filler.fill_page(form_page, PROFILE, sample_pdf)
    assert form_page.evaluate("window.wrongList || false") is False


def test_choice_question_is_reported_once_by_its_text(form_page, sample_pdf):
    report = filler.fill_page(form_page, PROFILE, sample_pdf)
    assert report.needs_you.count("Are you willing to travel?") == 1
    assert "Yes" not in report.needs_you
    assert not form_page.is_checked('input[name="travel"] >> nth=0')


def test_resume_goes_in_the_resume_input_only(form_page, sample_pdf):
    report = filler.fill_page(form_page, PROFILE, sample_pdf)
    assert report.resume_attached
    assert form_page.evaluate("document.getElementById('resume').files.length") == 1
    assert form_page.evaluate("document.getElementById('cover_letter').files.length") == 0


def test_no_pdf_means_no_upload(form_page):
    report = filler.fill_page(form_page, PROFILE, None)
    assert not report.resume_attached
    assert form_page.evaluate("document.getElementById('resume').files.length") == 0
