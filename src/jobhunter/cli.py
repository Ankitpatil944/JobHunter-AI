"""Command line interface: python -m jobhunter <command>."""
import argparse
import sys
from datetime import datetime, timedelta, timezone

from jobhunter import db
from jobhunter.config import load_yaml
from jobhunter.filter import Rules, apply_filters
from jobhunter.http import Http
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
    print("\nLatest run per source:")
    for row in conn.execute(
        """SELECT source, ok, fetched, added, message, MAX(started_at) AS started_at
           FROM source_runs GROUP BY source ORDER BY source"""
    ):
        state = "ok" if row["ok"] else "FAILED"
        print(f"  {row['source']:<16}{state:<8}{row['fetched']:>6} fetched{row['added']:>6} new  {row['started_at'][:16]}")
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

    args = parser.parse_args(argv)
    return args.func(args)
