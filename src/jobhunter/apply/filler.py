"""Fill an application page in a visible browser, then leave it for the person.

Safety rule: this module only sets field values and attaches a file. It never clicks a
button and never presses Enter, because either could submit the application. Its only
clicks are on a dropdown's input, to open it, and on a matching option in that dropdown.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from jobhunter.apply.fields import decide
from jobhunter.config import DATA_DIR, ROOT

BROWSERS_DIR = ROOT / "tools" / "browsers"
PROFILE_DIR = DATA_DIR / "browser-profile"
PAGE_TIMEOUT_MS = 60000
FORM_TIMEOUT_MS = 20000
OPTION_TIMEOUT_MS = 2500

READ_FIELD = """el => {
    const label = (el.labels && el.labels[0] && el.labels[0].innerText) || el.getAttribute('aria-label') || '';
    const named = (el.getAttribute('aria-labelledby') || '').split(' ').map(id => document.getElementById(id))
        .filter(Boolean).map(n => n.innerText).join(' ');
    const legend = el.closest('fieldset') && el.closest('fieldset').querySelector('legend');
    const leverLabel = el.closest('.application-question')
        && el.closest('.application-question').querySelector('.application-label');
    const question = (leverLabel && leverLabel.innerText) || (legend && legend.innerText) || '';
    const own = (label && !label.endsWith('-label') ? label : named);
    const isChoice = el.type === 'radio' || el.type === 'checkbox';
    return {tag: el.tagName, type: el.type, id: el.id, name: el.name, role: el.getAttribute('role'),
            label: (isChoice ? question || own : own || question) || el.name || '',
            required: el.required || el.getAttribute('aria-required') === 'true'};
}"""
HIGHLIGHT = "el => { el.style.outline = '3px solid #f5b301'; el.style.outlineOffset = '2px'; }"
BANNER = """() => {
    const note = document.createElement('div');
    note.textContent = 'JobHunter filled what it could. Yellow fields need you. Review everything, then click Submit yourself.';
    note.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:8px 16px;'
        + 'background:#1f2937;color:#fff;font:14px sans-serif;text-align:center;pointer-events:none';
    document.body.appendChild(note);
}"""
SKIPPED_TYPES = {"hidden", "submit", "button", "reset", "image", "search"}


@dataclass
class FillReport:
    filled: list[tuple[str, str]] = field(default_factory=list)
    needs_you: list[str] = field(default_factory=list)
    optional_blank: list[str] = field(default_factory=list)
    resume_attached: bool = False


def _clean(label: str) -> str:
    return " ".join(label.split()).rstrip("*✱ ")[:90]


def _pick_option(page, element, value: str) -> bool:
    """Type into a searchable dropdown and choose the option that matches exactly."""
    element.click(timeout=OPTION_TIMEOUT_MS)
    element.fill(value)
    # Visible only: forms keep other lists in the page, such as a hidden phone-country list.
    options = page.locator('[role="option"]:visible')
    try:
        options.first.wait_for(state="visible", timeout=OPTION_TIMEOUT_MS)
    except Exception:
        element.fill("")
        return False
    wanted = value.lower()
    exact, close = [], []
    for index in range(options.count()):
        option = options.nth(index)
        text = option.inner_text().strip().lower()
        # "Bengaluru" also matches "Bengaluru, Karnataka, India" and "India" matches "India +91",
        # but "India" never matches "Indiana" or "British Indian Ocean Territory".
        if text == wanted:
            exact.append(option)
        elif re.match(rf"{re.escape(wanted)}\s*(,|\+\d)", text):
            close.append(option)
    # "Yes" could mean "Yes, I am eligible" or "Yes, with sponsorship", so more than one close match is the person's call.
    chosen = exact[:1] or (close if len(close) == 1 else [])
    if chosen:
        chosen[0].click(timeout=OPTION_TIMEOUT_MS)
        return True
    # Closing the list with Escape is safe. Only Enter could submit.
    element.fill("")
    page.keyboard.press("Escape")
    return False


def _set_value(page, element, info: dict, value: str) -> bool:
    # A field that can't be set is flagged for the person. It must not stop the rest of the form.
    try:
        if info["tag"] == "SELECT":
            element.select_option(label=value, timeout=OPTION_TIMEOUT_MS)
        elif info["role"] == "combobox":
            return _pick_option(page, element, value)
        else:
            element.fill(value, timeout=OPTION_TIMEOUT_MS)
        return True
    except Exception:
        return False


def _is_resume_input(info: dict) -> bool:
    text = f"{info['id']} {info['name']} {info['label']}".lower()
    return "cover" not in text and ("resume" in text or " cv" in f" {text}")


def fill_page(page, profile: dict, pdf: Path | None, india_job: bool = True) -> FillReport:
    report = FillReport()
    flagged_groups: set[str] = set()
    for element in page.query_selector_all("input, textarea, select"):
        info = element.evaluate(READ_FIELD)
        label = _clean(info["label"])

        if info["type"] == "file":
            if pdf and not report.resume_attached and _is_resume_input(info):
                element.set_input_files(str(pdf))
                report.resume_attached = True
            continue
        if info["type"] in SKIPPED_TYPES or not (info["id"] or info["name"]):
            continue
        if not element.is_visible():
            continue

        # Tick boxes and radio buttons are always the person's own statement.
        if info["type"] in ("checkbox", "radio"):
            if info["required"]:
                element.evaluate(HIGHLIGHT)
                group = info["name"] or info["id"]
                if group not in flagged_groups:
                    flagged_groups.add(group)
                    report.needs_you.append(label)
            continue

        decision = decide(label, profile, india_job)
        if decision.status == "fill" and _set_value(page, element, info, decision.value):
            report.filled.append((label, decision.value))
        elif info["required"]:
            element.evaluate(HIGHLIGHT)
            report.needs_you.append(label)
        elif label:
            report.optional_blank.append(label)
    page.evaluate(BANNER)
    return report


def open_form(page, url: str) -> None:
    # Some forms keep loading trackers forever, so don't wait for the network to go quiet.
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
    page.wait_for_selector("input", timeout=FORM_TIMEOUT_MS)
    page.wait_for_timeout(1500)


def run_browser(url: str, profile: dict, pdf: Path | None, india_job: bool, supported: bool, on_ready) -> None:
    """Open a visible browser, fill the form if supported, and wait for the person to close it."""
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(BROWSERS_DIR)
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(PROFILE_DIR), headless=False, no_viewport=True)
        page = context.pages[0] if context.pages else context.new_page()
        if supported:
            # If filling fails, keep the browser open so the person can still apply by hand.
            try:
                open_form(page, url)
                on_ready(fill_page(page, profile, pdf, india_job))
            except Exception as exc:
                print(f"Couldn't fill the form: {str(exc).splitlines()[0]}")
                on_ready(None)
        else:
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            on_ready(None)
        context.wait_for_event("close", timeout=0)
