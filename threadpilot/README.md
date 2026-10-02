# ThreadPilot: the General Manager's Co-Pilot

[中文说明 / Chinese README](README.zh.md)

DSS5105 capstone, Track 1. An AI co-pilot for the general manager of a quick-response knitwear
factory: a scheduled morning briefing, multi-turn questions answered from fresh data, standing
watches, feasibility estimates with stated assumptions, and actions (chase-ups, notes, reminders)
that are confirmed before they happen and logged after.

Two rules run through the system: **the language model never does the arithmetic** (tools compute,
the model narrates), and **every number can be traced back to the rows it came from**.

| Part | What it is | Where |
|---|---|---|
| Backend | FastAPI service: intent classification, workflow engine, tools, data API, SQL agent, scheduled checks | `backend/` |
| Front end | Browser interface served by the backend at `/` | `frontend/` |
| Database | MySQL, schema managed with Alembic | `data/migrations/` |
| Seed data | 120 orders, 90 days of production, 8 workshops (business date 2026-04-01) | `data/*.csv` |
| Briefing demo | Simulator, morning briefing, executive dashboard with a built-in chat assistant; runs offline | `simulation/`, `demo/` |
| ML | Order-delay probability model and feasibility tools | `ml/` |

---

## Quick look, no setup

Open **`demo/briefing_demo.html`** in a browser. It needs no server, database or API key.
It shows two simulated weeks of morning briefings, an executive dashboard, and the "Ask ThreadPilot"
chat assistant. To rebuild it:

```bash
python -m simulation.render_demo --days 14
```

The chat in this demo uses built-in tools, not a language model. See
[docs/chat_tools.md](docs/chat_tools.md) for its tool specification and validation.

---

## Run the full system

You need Python 3.12 or 3.13, [uv](https://docs.astral.sh/uv/), and MySQL 8 (local or Docker).

### Option A: local development (the team's main setup)

All commands run in `backend/`.

```bash
cd backend
uv sync --locked --group dev           # exact versions from uv.lock
cp .env.example .env                   # Windows: Copy-Item .env.example .env
```

Generate the application password, the read-only AI password and the admin token
(it prints values; nothing is written to disk):

```bash
python -c "import secrets; names=['MYSQL_APP_PASSWORD','MYSQL_AI_PASSWORD','DATA_API_TOKEN']; print('\n'.join(n+'='+secrets.token_hex(24) for n in names))"
```

Put `DATA_API_TOKEN` and your `OPENAI_API_KEY` in `backend/.env`, and put the two passwords into
`DATABASE_URL` and `AI_DATABASE_URL`. The three database passwords (root, application, AI) must all
be different. Then create the database, accounts and tables, and load the seed data.
On macOS/Linux (bash), the passwords are typed, not stored:

```bash
export MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 MYSQL_DATABASE=threadpilot
read -r -s -p 'MySQL root password: ' MYSQL_ROOT_PASSWORD; echo
read -r -s -p 'Application password: ' MYSQL_APP_PASSWORD; echo
read -r -s -p 'AI read-only password: ' MYSQL_AI_PASSWORD; echo
export MYSQL_ROOT_PASSWORD MYSQL_APP_PASSWORD MYSQL_AI_PASSWORD
uv run python -m scripts.provision_mysql
unset MYSQL_ROOT_PASSWORD MYSQL_APP_PASSWORD MYSQL_AI_PASSWORD
uv run python -m scripts.init_db --skip-migrate --seed-existing    # expect 120 / 360 / 8 rows
```

On Windows PowerShell, set the same variables with `$env:NAME = '<value>'`, run the same two
`uv run` commands, then remove them with `Remove-Item Env:MYSQL_ROOT_PASSWORD, Env:MYSQL_APP_PASSWORD, Env:MYSQL_AI_PASSWORD`.
Never paste real passwords into a file that is committed.

Start the server and open <http://127.0.0.1:8000>:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
# or: sh start.sh --reload        (Windows: ./start.ps1 -Reload)
```

Check it: <http://127.0.0.1:8000/api/v1/health> should return `status: ok`, and
<http://127.0.0.1:8000/api/snapshot> should list 120 orders. API docs: `/docs`.

### Option B: Docker Compose

From this folder (`threadpilot/`):

```bash
cp .env.example .env        # fill in three different database passwords, DATA_API_TOKEN, OPENAI_API_KEY
docker compose up --build -d
docker compose run --rm backend python -m scripts.init_db --skip-migrate --seed-existing
```

Then open <http://127.0.0.1:8000>. The `provision` service creates the database, accounts and tables;
the second command loads the seed data. The ports are bound to `127.0.0.1` only.

### The business clock

`BUSINESS_NOW` decides what "today" is. The seed data ends on 2026-03-31, so for a reproducible run use
`BUSINESS_NOW=2026-04-01T08:00:00+08:00` (the timezone is required). `live` uses the real clock and only
makes sense once the database receives current data; with the seed data it makes every order look months late.

---

## Tests

```bash
cd backend && uv run --locked pytest -q
```

Backend tests use temporary SQLite databases and mocked model calls, so they need no MySQL and no API key.
The MySQL integration test is skipped unless `TEST_MYSQL_URL` points to an isolated test database.

```bash
python -m pip install pytest playwright && python -m playwright install chromium
python -m pytest -q tests/test_simulation.py tests/test_chat.py
```

These cover the simulator, the briefing builder and the dashboard chat (in a headless browser).
GitHub Actions runs all of the above, plus the repository safety check, on every push and pull request.
MySQL provisioning and Docker are not exercised by CI.

**Before every push:** `python scripts/check_repo.py`. It fails on secrets, `.env` files, runtime data,
oversized files and shell scripts with Windows line endings.

---

## Documentation

| Topic | Document |
|---|---|
| Team workflow, branches, pull requests | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Publishing to GitHub step by step | [docs/GITHUB_GUIDE.md](docs/GITHUB_GUIDE.md) |
| API reference | [backend/API_DOCUMENTATION.md](backend/API_DOCUMENTATION.md), [docs/openapi.json](docs/openapi.json), [backend/STREAMING_API.md](backend/STREAMING_API.md) |
| Architecture and intent workflow (Chinese) | [docs/workflow_design.md](docs/workflow_design.md), [docs/INTENT_WORKFLOW.md](docs/INTENT_WORKFLOW.md) |
| Data pipeline and dictionary | [docs/data_pipeline.md](docs/data_pipeline.md), [data/data_dictionary.md](data/data_dictionary.md) |
| Live model verification | [docs/live_model_verification.md](docs/live_model_verification.md) |
| Dashboard chat: tools, limits, validation | [docs/chat_tools.md](docs/chat_tools.md) |
| Dashboard design review | [docs/DASHBOARD_REVIEW.md](docs/DASHBOARD_REVIEW.md) |
| Code review and known issues | [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md) |
| ML delay model | [ml/README.md](ml/README.md) |

---

## Repository layout

```
threadpilot/
├── backend/        FastAPI app (app/), maintenance scripts (scripts/), tests (tests/), uv.lock
├── frontend/       browser interface served by the backend
├── data/           seed CSVs, data dictionary, Alembic migrations; raw/ and snapshots/ stay local
├── simulation/     day-by-day simulator, briefing builder, demo page and chat assistant
├── demo/           generated demo page (open directly)
├── briefings/      generated morning briefings (JSON), one per simulated day
├── ml/             delay-probability model and feasibility tools
├── prototypes/     early single-file prototype, kept for reference
├── tests/          simulator, briefing and chat tests; browser end-to-end tests (e2e/)
├── scripts/        check_repo.py pre-push safety check
├── docs/           documentation
├── Dockerfile, docker-compose.yml, requirements.txt (exported from backend/uv.lock)
```

## Notes and limits

* The data holds no prices, revenue or worker names; the co-pilot says so instead of inventing figures.
* Secrets live only in `.env` files, which are git-ignored. Share `.env.example`, never `.env`.
* `requirements.txt` is exported from `backend/uv.lock` for the Docker image. After changing dependencies,
  run `uv lock` and re-export (the command is at the top of `requirements.txt`).

## Team

Matthew, LIU JING, Kevin Royce Thomson, Anqi Lin, Wendy, and one teammate still to be listed under
their real name. NUS MSc, DSS5105.
