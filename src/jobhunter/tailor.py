"""Set up and verify a tailored resume for one job."""
import shutil
from dataclasses import dataclass
from pathlib import Path

from jobhunter import db, latex
from jobhunter.config import ROOT, load_yaml

BASE_DIR = ROOT / "resumes" / "base"
TAILORED_DIR = ROOT / "resumes" / "tailored"


@dataclass
class TailorReport:
    passed: bool
    used_base: bool
    pdf: Path | None
    blocking: list[str]
    needs_review: list[str]
    notes: list[str]


def base_resumes(base_dir: Path = BASE_DIR) -> list[str]:
    return sorted(p.stem for p in base_dir.glob("*.tex"))


def start(job_id: int, resume: str, base_dir: Path = BASE_DIR, tailored_dir: Path = TAILORED_DIR) -> Path:
    """Copy a base resume into the job's folder for editing. An existing draft is kept."""
    source = base_dir / f"{resume}.tex"
    if not source.exists():
        raise FileNotFoundError(f"No base resume named {resume}. Available: {base_resumes(base_dir)}")
    folder = tailored_dir / str(job_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "resume.tex"
    if not target.exists():
        shutil.copyfile(source, target)
    (folder / "base.txt").write_text(resume, encoding="utf-8")
    return target


def check(job_id: int, approved: bool = False, base_dir: Path = BASE_DIR, tailored_dir: Path = TAILORED_DIR,
          known_skills: list[str] | None = None) -> TailorReport:
    """Run every check. If they fail, the job's PDF is the untouched base resume."""
    folder = tailored_dir / str(job_id)
    resume = (folder / "base.txt").read_text(encoding="utf-8").strip()
    base_path = base_dir / f"{resume}.tex"
    base_tex = base_path.read_text(encoding="utf-8")
    tailored_path = folder / "resume.tex"
    tailored_tex = tailored_path.read_text(encoding="utf-8")
    if known_skills is None:
        known_skills = load_yaml("skills.yaml").get("skills") or []

    facts = latex.check_facts(base_tex, tailored_tex, known_skills)
    blocking = list(facts.blocking)
    (folder / "changes.diff").write_text(latex.make_diff(base_tex, tailored_tex, base_path.name), encoding="utf-8")

    build = folder / "build"
    base_build = latex.compile_tex(base_path, build / "base", search_path=base_dir)
    if not base_build.ok:
        # Without a compiled base there is no PDF to fall back on.
        return TailorReport(False, False, None, [f"The base resume failed to compile:\n{base_build.log[-1500:]}"],
                            facts.needs_review, facts.notes)

    tailored_build = latex.compile_tex(tailored_path, build / "tailored", search_path=base_dir)
    if tailored_build.ok:
        blocking += latex.check_pdf(tailored_build.pdf, base_build.pdf, tailored_tex).blocking
    else:
        blocking.append(f"The tailored resume failed to compile:\n{tailored_build.log[-1500:]}")

    passed = not blocking and (approved or not facts.needs_review)
    chosen = tailored_build.pdf if passed else base_build.pdf
    output = folder / "resume.pdf"
    shutil.copyfile(chosen, output)
    return TailorReport(passed, not passed, output, blocking, facts.needs_review, facts.notes)


def save_score(conn, job_id: int, score: int, resume: str, reason: str, gaps: str = "") -> None:
    if not 0 <= score <= 100:
        raise ValueError("Score must be between 0 and 100.")
    conn.execute(
        """INSERT INTO scores (job_id, score, resume, reason, gaps, scored_at) VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET score = excluded.score, resume = excluded.resume,
               reason = excluded.reason, gaps = excluded.gaps, scored_at = excluded.scored_at""",
        (job_id, score, resume, reason, gaps, db.now()),
    )
