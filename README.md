# JobHunter-AI

Finds software, backend, AI, ML and data engineering jobs, tailors a LaTeX resume for each one, and pre-fills the application form. A person always reviews the form and clicks Submit.

```
Job feeds -> keyword filter -> Claude scores -> Claude tailors -> checks -> form pre-fill -> you submit
 (Python)      (Python)        (Claude Code)    (Claude Code)    (Python)   (Playwright)
```

## Daily use

```powershell
.venv\Scripts\python -m jobhunter fetch          # get new jobs
# In Claude Code: /triage, then /tailor <job id>
.venv\Scripts\python -m jobhunter apply <job id> # pre-fill; you review and click Submit
.venv\Scripts\python -m jobhunter mark <job id> applied
.venv\Scripts\python -m jobhunter status
```

## Job sources

Sites whose terms ban scraping or automated access aren't fetched, even when `robots.txt` allows it, because the risk to the person's account isn't worth it. Terms were read on 2026-11-03 and can change.

| Status | Sources | Route |
|---|---|---|
| Fetched | RemoteOK, Remotive, Himalayas, Jobicy, Arbeitnow, We Work Remotely, Hacker News Who's Hiring, NoDesk, Landing.jobs | Public APIs and published feeds |
| Fetched | Greenhouse, Lever, Ashby, Workday | Public job APIs, per company in `config/companies.yaml` |
| On demand | Indeed | Claude's Indeed connector, loaded with `import-jobs` |
| Terms ban scraping | Hirist, Cutshort, iimjobs, Internshala, Foundit, YC, Wellfound, DailyRemote, Remote Rocketship | Not automated; open links yourself |
| Terms unread | Naukri, Instahyre, Relocate.me, Working Nomads, GermanTechJobs, SwissDevJobs | Off until someone reads their terms |
| Blocked or undecided | TokyoDev (refused requests), Japan Dev, NoDesk's other categories, aijobs.net (no usable feed found) | Not connected |
| Not automated | LinkedIn, Glassdoor | Links only |

## Setup

Personal data stays local and is gitignored: `config/profile.yaml`, `resumes/`, `data/`. Copy `config/profile.example.yaml` to `config/profile.yaml` and put your `.tex` resumes in `resumes/base/`.
