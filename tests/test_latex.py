import pytest

from jobhunter import db, latex, tailor

BASE = r"""\documentclass{article}
\begin{document}
\section*{Experience}
Acme Corp, Backend Engineer, 2021
\begin{itemize}
\item Built Python services handling 500 requests per second
\item Reduced database costs using PostgreSQL
% \item Used Kubernetes in a side project
\end{itemize}
\end{document}
"""
SKILLS = ["Python", "PostgreSQL", "Kubernetes", "C++", "Go"]
needs_compiler = pytest.mark.skipif(not latex.TECTONIC.exists(), reason="Tectonic not installed")


def test_reordering_and_rewording_is_clean():
    tailored = BASE.replace(
        r"\item Built Python services handling 500 requests per second",
        r"\item Developed backend Python services serving 500 requests per second",
    )
    result = latex.check_facts(BASE, tailored, SKILLS)
    assert not result.blocking and not result.needs_review


def test_new_metric_is_flagged():
    tailored = BASE.replace("500 requests", "5000 requests")
    assert "New number or date: 5000" in latex.check_facts(BASE, tailored, SKILLS).needs_review


def test_changed_date_is_flagged():
    assert "New number or date: 2019" in latex.check_facts(BASE, BASE.replace("2021", "2019"), SKILLS).needs_review


def test_new_skill_is_flagged():
    tailored = BASE.replace("using PostgreSQL", "using PostgreSQL and C++")
    assert "New skill: C++" in latex.check_facts(BASE, tailored, SKILLS).needs_review


def test_commented_out_skill_is_not_evidence():
    tailored = BASE.replace("using PostgreSQL", "using PostgreSQL on Kubernetes")
    assert "New skill: Kubernetes" in latex.check_facts(BASE, tailored, SKILLS).needs_review


def test_short_skill_needs_whole_word():
    tailored = BASE.replace("Reduced database", "Good database")
    assert not any("Go" in item for item in latex.check_facts(BASE, tailored, SKILLS).needs_review)


def test_moving_a_word_to_the_end_of_a_sentence_is_not_new():
    base = BASE.replace("using PostgreSQL", "using PostgreSQL and FastAPI today")
    tailored = BASE.replace("using PostgreSQL", "using PostgreSQL today and FastAPI.")
    assert not latex.check_facts(base, tailored, SKILLS).notes


def test_ordinary_words_are_not_skills():
    tailored = BASE.replace("Reduced database", "Helped the rest of the team go faster on database")
    assert not latex.check_facts(BASE, tailored, ["REST", "Go"]).needs_review


def test_current_role_reads_the_present_job():
    tex = (r"\begin{document}" "\n"
           r"\textbf{Old Intern \,|\, Past Co} \hfill Sep 2024 -- Dec 2024\\" "\n"
           r"\textbf{Software Engineer Intern \,|\, Sttarkel Technologies} \hfill Jun 2025 -- Present\\" "\n"
           r"\end{document}")
    assert latex.current_role(tex) == ("Software Engineer Intern", "Sttarkel Technologies")
    assert latex.current_role(BASE) is None


def test_preamble_change_blocks():
    tailored = BASE.replace(r"\documentclass{article}", "\\documentclass{article}\n\\usepackage{xcolor}")
    assert latex.check_facts(BASE, tailored, SKILLS).blocking


def test_new_employer_is_noted():
    notes = latex.check_facts(BASE, BASE.replace("Acme Corp", "Google Corp"), SKILLS).notes
    assert any("Google" in note for note in notes)


def test_dropped_bullet_is_noted():
    tailored = BASE.replace("\\item Reduced database costs using PostgreSQL\n", "")
    assert any("Bullets" in note for note in latex.check_facts(BASE, tailored, SKILLS).notes)


def test_save_score_updates_and_validates():
    conn = db.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = OFF")
    tailor.save_score(conn, 1, 70, "backend", "ok")
    tailor.save_score(conn, 1, 80, "backend", "better")
    assert conn.execute("SELECT score FROM scores").fetchall()[0]["score"] == 80
    with pytest.raises(ValueError):
        tailor.save_score(conn, 1, 101, "backend", "bad")


@pytest.fixture
def folders(tmp_path):
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    (base_dir / "backend.tex").write_text(BASE, encoding="utf-8")
    return {"base_dir": base_dir, "tailored_dir": tmp_path / "tailored"}


def edit(folders, change):
    path = tailor.start(1, "backend", **folders)
    path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")


def test_start_keeps_existing_draft(folders):
    edit(folders, lambda t: t.replace("Acme", "Acme Inc"))
    assert "Acme Inc" in tailor.start(1, "backend", **folders).read_text(encoding="utf-8")


def test_start_rejects_unknown_resume(folders):
    with pytest.raises(FileNotFoundError):
        tailor.start(1, "nope", **folders)


@needs_compiler
def test_base_filename_with_spaces_compiles_cleanly(tmp_path):
    source = tmp_path / "Backend engineer.tex"
    source.write_text(BASE.replace(r"\begin{document}", "\\usepackage{hyperref}\n\\begin{document}"), encoding="utf-8")
    result = latex.compile_tex(source, tmp_path / "out")
    assert result.ok and "os error" not in result.log


@needs_compiler
def test_clean_edit_passes_and_uses_tailored_pdf(folders):
    edit(folders, lambda t: t.replace("Built Python", "Developed Python"))
    report = tailor.check(1, known_skills=SKILLS, **folders)
    assert report.passed and not report.used_base and report.pdf.exists()
    assert "Developed" in (folders["tailored_dir"] / "1" / "changes.diff").read_text(encoding="utf-8")
    assert "Developed" in latex.PdfReader(str(report.pdf)).pages[0].extract_text()


@needs_compiler
def test_invented_facts_fall_back_to_base_until_approved(folders):
    edit(folders, lambda t: t.replace("500 requests", "9000 requests").replace("using PostgreSQL", "using PostgreSQL and C++"))
    report = tailor.check(1, known_skills=SKILLS, **folders)
    assert not report.passed and report.used_base
    assert "9000" not in latex.PdfReader(str(report.pdf)).pages[0].extract_text()
    assert tailor.check(1, approved=True, known_skills=SKILLS, **folders).passed


@needs_compiler
def test_overflowing_resume_is_blocked_even_if_approved(folders):
    edit(folders, lambda t: t.replace(r"\end{itemize}", "\\item Built Python services\n" * 120 + r"\end{itemize}"))
    report = tailor.check(1, approved=True, known_skills=SKILLS, **folders)
    assert not report.passed and report.used_base
    assert any("pages" in item for item in report.blocking)
    assert latex.page_count(report.pdf) == 1


@needs_compiler
def test_broken_latex_falls_back_to_base(folders):
    edit(folders, lambda t: t.replace(r"\end{itemize}", r"\badcommand \end{itemize}"))
    report = tailor.check(1, known_skills=SKILLS, **folders)
    assert not report.passed and report.used_base and report.pdf.exists()
    assert any("failed to compile" in item for item in report.blocking)
