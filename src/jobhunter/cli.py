"""Command line interface: python -m jobhunter <command>."""
import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobhunter import db, latex, tailor
from jobhunter.apply.fields import detect_system
from jobhunter.config import CONFIG_DIR, load_yaml
from jobhunter.filter import Rules, apply_filters
from jobhunter.http import Http
from jobhunter.models import Job
from jobhunter.sources import SOURCES


def cmd_fetch(args) -> int:
    conn = db.connect()
    companies = load_yaml("companies.yaml")
    names = args.source or list(SOURCES)
    print(f"{'source':<16}{'fetched':>8}{'new':>7}  note")
    for name in names:
        module = SOURCES[name]
        last = db.last_success(conn, name)
        interval = timedelta(hours=module.MIN_INTERVAL_HOURS)
        if last and not args.force and datetime.now(timezone.utc) - last < interval:
            print(f"{name:<16}{'-':>8}{'-':>7}  skipped, fetched under {module.MIN_INTERVAL_HOURS}h ago")
            continue
        http = Http()
        try:
            jobs = module.fetch(http, companies)
            added = sum(db.upsert_job(conn, job) for job in jobs)
            note = "; ".join(http.warnings)
            db.record_run(conn, name, True, len(jobs), added, note)
            print(f"{name:<16}{len(jobs):>8}{added:>7}  {note}")
        except Exception as exc:  # One failing source must not stop the run.
            db.record_run(conn, name, False, message=str(exc)[:500])
            print(f"{name:<16}{'FAILED':>8}{'-':>7}  {exc}")
        finally:
            http.close()
            conn.commit()
    relevant = apply_filters(conn, Rules(load_yaml("search.yaml")))
    conn.commit()
    print(f"\n{relevant} relevant jobs after filtering")
    return 0


def cmd_import(args) -> int:
    """Load jobs from a JSON list, such as Indeed connector results, and re-run the filters."""
    conn = db.connect()
    items = json.loads(Path(args.file).read_text(encoding="utf-8"))
    added = 0
    for item in items:
        added += db.upsert_job(conn, Job(
            source=args.source,
            url=item["url"],
            company=item.get("company") or "",
            title=item["title"],
            location=item.get("location") or "",
            remote=bool(item.get("remote")),
            description=item.get("description") or "",
            posted_at=item.get("posted_at"),
        ))
    db.record_run(conn, args.source, True, len(items), added)
    relevant = apply_filters(conn, Rules(load_yaml("search.yaml")))
    conn.commit()
    print(f"{len(items)} read, {added} new. {relevant} relevant jobs after filtering")
    return 0


def cmd_list(args) -> int:
    conn = db.connect()
    sql = "SELECT j.*, s.score FROM jobs j LEFT JOIN scores s ON s.job_id = j.id WHERE j.relevant = 1"
    params: list = []
    if args.market:
        sql += " AND (',' || j.markets || ',') LIKE ?"
        params.append(f"%,{args.market},%")
    if args.role:
        sql += " AND j.role = ?"
        params.append(args.role)
    if args.eligibility:
        sql += " AND j.eligibility = ?"
        params.append(args.eligibility)
    if args.unscored:
        sql += " AND s.score IS NULL"
    sql += " ORDER BY s.score DESC NULLS LAST, j.posted_at DESC LIMIT ?"
    params.append(args.limit)
    for row in conn.execute(sql, params):
        score = row["score"] if row["score"] is not None else "-"
        print(
            f"{row['id']:>6} {score:>3} {row['eligibility']:<6} {row['role'] or '':<9} "
            f"{row['company'][:22]:<22} {row['title'][:48]:<48} {row['location'][:24]:<24} [{row['source']}]"
        )
    return 0


def cmd_show(args) -> int:
    row = db.connect().execute("SELECT * FROM jobs WHERE id = ?", (args.job_id,)).fetchone()
    if not row:
        print(f"No job with id {args.job_id}", file=sys.stderr)
        return 1
    for key in ("company", "title", "location", "remote", "markets", "eligibility", "role",
                "posted_at", "source", "also_on", "url", "filter_reason"):
        print(f"{key}: {row[key]}")
    print(f"\n{row['description']}")
    return 0


def cmd_status(args) -> int:
    conn = db.connect()
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    relevant = conn.execute("SELECT COUNT(*) FROM jobs WHERE relevant = 1").fetchone()[0]
    print(f"Jobs stored: {total}\nRelevant: {relevant}\n\nRelevant by market:")
    counts: dict[tuple[str, str], int] = {}
    for row in conn.execute("SELECT markets, eligibility FROM jobs WHERE relevant = 1"):
        for market in row["markets"].split(","):
            counts[(market, row["eligibility"])] = counts.get((market, row["eligibility"]), 0) + 1
    for (market, eligibility), count in sorted(counts.items()):
        print(f"  {market:<16}{eligibility:<8}{count:>6}")
    print("\nApplications:")
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM applications GROUP BY status ORDER BY status"):
        print(f"  {row['status']:<16}{row['n']:>6}")
    due = conn.execute(
        """SELECT j.id, j.company, j.title, a.follow_up_on FROM applications a JOIN jobs j ON j.id = a.job_id
           WHERE a.status = 'applied' AND a.follow_up_on <= ? ORDER BY a.follow_up_on""",
        (datetime.now(timezone.utc).date().isoformat(),),
    ).fetchall()
    if due:
        print("\nFollow-ups due:")
        for row in due:
            print(f"  {row['id']:>6} {row['company']}: {row['title']} (since {row['follow_up_on']})")
    print("\nLatest run per source:")
    for row in conn.execute(
        """SELECT source, ok, fetched, added, message, MAX(started_at) AS started_at
           FROM source_runs GROUP BY source ORDER BY source"""
    ):
        state = "ok" if row["ok"] else "FAILED"
        print(f"  {row['source']:<16}{state:<8}{row['fetched']:>6} fetched{row['added']:>6} new  {row['started_at'][:16]}")
    return 0


def cmd_score(args) -> int:
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM jobs WHERE id = ?", (args.job_id,)).fetchone():
        print(f"No job with id {args.job_id}", file=sys.stderr)
        return 1
    tailor.save_score(conn, args.job_id, args.score, args.resume, args.reason, args.gaps)
    conn.commit()
    print(f"Saved score {args.score} for job {args.job_id}")
    return 0


def cmd_tailor_start(args) -> int:
    print(tailor.start(args.job_id, args.resume))
    return 0


def cmd_tailor_check(args) -> int:
    report = tailor.check(args.job_id, approved=args.approved)
    for label, items in (("BLOCKED", report.blocking), ("NEEDS REVIEW", report.needs_review), ("NOTE", report.notes)):
        for item in items:
            print(f"{label}: {item}")
    if report.passed:
        print(f"PASSED. Tailored PDF: {report.pdf}")
        return 0
    if report.pdf:
        print(f"NOT PASSED. Using the untouched base resume: {report.pdf}")
    return 1


def _named_pdf(job_id: int, pdf: Path, profile: dict) -> Path:
    """Copy the PDF to a name that looks right to the recruiter who receives it."""
    name = profile.get("name") or {}
    stem = "_".join(str(p).strip() for p in (name.get("first"), name.get("last")) if p)
    target = tailor.TAILORED_DIR / str(job_id) / f"{stem or 'Candidate'}_Resume.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, target)
    return target


def _with_resume_role(profile: dict, job_id: int) -> dict:
    """Titles differ between resumes, so the form must say what the attached resume says."""
    tex = tailor.TAILORED_DIR / str(job_id) / "resume.tex"
    role = latex.current_role(tex.read_text(encoding="utf-8")) if tex.exists() else None
    if not role:
        return profile
    work = {**(profile.get("work") or {}), "current_title": role[0], "current_company": role[1]}
    return {**profile, "work": work}


def _print_report(report) -> None:
    if report is None:
        print("This site isn't supported for pre-filling, so the page was only opened.")
    else:
        print(f"Filled {len(report.filled)} fields:")
        for label, value in report.filled:
            print(f"  {label}: {value}")
        print(f"Resume attached: {'yes' if report.resume_attached else 'NO, attach it yourself'}")
        print(f"Needs you ({len(report.needs_you)}, highlighted in yellow):")
        for label in report.needs_you:
            print(f"  {label}")
        if report.optional_blank:
            print(f"Optional and left blank: {len(report.optional_blank)}")
    print("\nNothing has been submitted. Review the page, click Submit yourself, then close the browser.")
    print("Afterwards, record it with: python -m jobhunter mark <id> applied")


def cmd_apply(args) -> int:
    from jobhunter.apply.filler import run_browser

    conn = db.connect()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (args.job_id,)).fetchone()
    if not row:
        print(f"No job with id {args.job_id}", file=sys.stderr)
        return 1
    if not (CONFIG_DIR / "profile.yaml").exists():
        print("config/profile.yaml is missing. Copy config/profile.example.yaml and fill it in.", file=sys.stderr)
        return 1
    profile = _with_resume_role(load_yaml("profile.yaml"), args.job_id)
    pdf = Path(args.pdf) if args.pdf else tailor.TAILORED_DIR / str(args.job_id) / "resume.pdf"
    if not pdf.exists():
        print(f"No resume at {pdf}. Run /tailor {args.job_id} first, or pass --pdf.", file=sys.stderr)
        return 1

    url = row["apply_url"] or row["url"]
    supported = detect_system(url) is not None
    named = _named_pdf(args.job_id, pdf, profile)
    print(f"{row['company']}: {row['title']}\nForm: {url}\nResume: {named}\n")
    db.set_application(conn, args.job_id, "prefilled", resume_path=str(named))
    conn.commit()
    run_browser(url, profile, named if supported else None, row["markets"].startswith("india"), supported, _print_report)
    return 0


def cmd_mark(args) -> int:
    conn = db.connect()
    if not conn.execute("SELECT 1 FROM jobs WHERE id = ?", (args.job_id,)).fetchone():
        print(f"No job with id {args.job_id}", file=sys.stderr)
        return 1
    applied_at = follow_up = None
    if args.status == "applied":
        today = datetime.now(timezone.utc)
        applied_at = today.isoformat()
        follow_up = (today + timedelta(days=args.follow_up_days)).date().isoformat()
    db.set_application(conn, args.job_id, args.status, notes=args.notes, applied_at=applied_at, follow_up_on=follow_up)
    conn.commit()
    print(f"Job {args.job_id}: {args.status}" + (f", follow up on {follow_up}" if follow_up else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="jobhunter")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="get new jobs from all sources")
    fetch.add_argument("--source", action="append", choices=sorted(SOURCES))
    fetch.add_argument("--force", action="store_true", help="ignore the minimum fetch interval")
    fetch.set_defaults(func=cmd_fetch)

    importer = sub.add_parser("import-jobs", help="load jobs from a JSON file, such as connector results")
    importer.add_argument("file")
    importer.add_argument("--source", default="indeed")
    importer.set_defaults(func=cmd_import)

    listing = sub.add_parser("list", help="list relevant jobs")
    listing.add_argument("--market", choices=["india_onsite", "india_remote", "global_remote", "visa_sponsor"])
    listing.add_argument("--role")
    listing.add_argument("--eligibility", choices=["open", "check"])
    listing.add_argument("--unscored", action="store_true")
    listing.add_argument("--limit", type=int, default=50)
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="show one job in full")
    show.add_argument("job_id", type=int)
    show.set_defaults(func=cmd_show)

    status = sub.add_parser("status", help="show counts and source health")
    status.set_defaults(func=cmd_status)

    score = sub.add_parser("score", help="record a job's match score")
    score.add_argument("job_id", type=int)
    score.add_argument("score", type=int)
    score.add_argument("--resume", required=True)
    score.add_argument("--reason", required=True)
    score.add_argument("--gaps", default="")
    score.set_defaults(func=cmd_score)

    tailor_start = sub.add_parser("tailor-start", help="copy a base resume into a job's folder")
    tailor_start.add_argument("job_id", type=int)
    tailor_start.add_argument("resume")
    tailor_start.set_defaults(func=cmd_tailor_start)

    tailor_check = sub.add_parser("tailor-check", help="compile and check a tailored resume")
    tailor_check.add_argument("job_id", type=int)
    tailor_check.add_argument("--approved", action="store_true",
                              help="the person has reviewed the flagged new numbers and skills")
    tailor_check.set_defaults(func=cmd_tailor_check)

    apply = sub.add_parser("apply", help="pre-fill an application in a browser; you click Submit")
    apply.add_argument("job_id", type=int)
    apply.add_argument("--pdf", help="resume to attach, instead of the job's tailored PDF")
    apply.set_defaults(func=cmd_apply)

    mark = sub.add_parser("mark", help="record what happened with an application")
    mark.add_argument("job_id", type=int)
    mark.add_argument("status", choices=["applied", "skipped", "interview", "rejected", "offer"])
    mark.add_argument("--notes")
    mark.add_argument("--follow-up-days", type=int, default=7)
    mark.set_defaults(func=cmd_mark)

    args = parser.parse_args(argv)
    return args.func(args)
