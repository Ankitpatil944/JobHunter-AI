"""Compile resumes and check that tailored versions add no new facts."""
import difflib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from jobhunter.config import ROOT

TECTONIC = ROOT / "tools" / "tectonic" / "tectonic.exe"
CACHE_DIR = ROOT / ".cache" / "tectonic"
BEGIN_DOCUMENT = r"\begin{document}"
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
MIN_TEXT_MATCH = 0.8


@dataclass
class Compiled:
    ok: bool
    pdf: Path | None
    log: str


@dataclass
class CheckResult:
    blocking: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def compile_tex(tex: Path, outdir: Path, search_path: Path | None = None) -> Compiled:
    outdir.mkdir(parents=True, exist_ok=True)
    # hyperref can't open its .out file when the name has spaces, so compile a copy.
    if " " in tex.name:
        safe = outdir / "input.tex"
        shutil.copyfile(tex, safe)
        search_path = search_path or tex.parent
        tex = safe
    command = [str(TECTONIC), "--outdir", str(outdir), "--chatter", "minimal"]
    if search_path:
        command += ["-Z", f"search-path={search_path}"]
    result = subprocess.run(
        command + [str(tex)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "TECTONIC_CACHE_DIR": str(CACHE_DIR)},
    )
    pdf = outdir / f"{tex.stem}.pdf"
    return Compiled(result.returncode == 0 and pdf.exists(), pdf if pdf.exists() else None, result.stdout + result.stderr)


def strip_comments(tex: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", tex)


def split_document(tex: str) -> tuple[str, str]:
    """Return (preamble, body). A file without \\begin{document} is all preamble."""
    head, sep, tail = tex.partition(BEGIN_DOCUMENT)
    return (head, tail) if sep else (tex, "")


def visible_body(tex: str) -> str:
    """The document body without comments, so a commented-out fact can't count as evidence."""
    return strip_comments(split_document(tex)[1])


def plain_words(tex_body: str) -> list[str]:
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", tex_body)
    # Trailing punctuation isn't part of a word, or "FastAPI." reads as new next to "FastAPI".
    return [w.rstrip(".-") for w in re.findall(r"[A-Za-z][A-Za-z+#.-]{2,}", text)]


def _contains_term(term: str, text: str) -> bool:
    # Short names need exact case, so "the rest" and "go" don't count as REST and Go.
    flags = 0 if len(term) <= 4 else re.I
    return re.search(rf"(?<![A-Za-z0-9+#]){re.escape(term)}(?![A-Za-z0-9+#])", text, flags) is not None


def check_facts(base_tex: str, tailored_tex: str, known_skills: list[str]) -> CheckResult:
    result = CheckResult()
    if split_document(base_tex)[0].strip() != split_document(tailored_tex)[0].strip():
        result.blocking.append("The preamble or template changed.")

    base = visible_body(base_tex)
    tailored = visible_body(tailored_tex)
    if not tailored.strip():
        result.blocking.append("The document body is empty.")
        return result

    for number in sorted(set(NUMBER.findall(tailored)) - set(NUMBER.findall(base))):
        result.needs_review.append(f"New number or date: {number}")
    for skill in known_skills:
        if _contains_term(skill, tailored) and not _contains_term(skill, base):
            result.needs_review.append(f"New skill: {skill}")

    base_words = {w.lower() for w in plain_words(base)}
    new_names = sorted({w for w in plain_words(tailored) if w[0].isupper() and w.lower() not in base_words})
    if new_names:
        result.notes.append("New capitalized words, check they aren't new facts: " + ", ".join(new_names))

    base_items, items = base.count(r"\item"), tailored.count(r"\item")
    if items < base_items:
        result.notes.append(f"Bullets went from {base_items} to {items}.")
    return result


def page_count(pdf: Path) -> int:
    return len(PdfReader(str(pdf)).pages)


def text_match_ratio(pdf: Path, tex: str) -> float:
    """Share of the resume's words that can be read back from the PDF, as applicant systems do."""
    extracted = " ".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages).lower()
    words = {w.lower().strip(".-") for w in plain_words(visible_body(tex))}
    words = {w for w in words if len(w) > 3}
    if not words:
        return 0.0
    return sum(w in extracted for w in words) / len(words)


def check_pdf(tailored_pdf: Path, base_pdf: Path, tailored_tex: str) -> CheckResult:
    result = CheckResult()
    pages, limit = page_count(tailored_pdf), page_count(base_pdf)
    if pages > limit:
        result.blocking.append(f"The PDF has {pages} pages; the base resume has {limit}.")
    ratio = text_match_ratio(tailored_pdf, tailored_tex)
    if ratio < MIN_TEXT_MATCH:
        result.blocking.append(f"Only {ratio:.0%} of the resume's words can be read back from the PDF.")
    return result


def make_diff(base_tex: str, tailored_tex: str, base_name: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            base_tex.splitlines(), tailored_tex.splitlines(), f"base/{base_name}", "tailored/resume.tex", lineterm=""
        )
    )
