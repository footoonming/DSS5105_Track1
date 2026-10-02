# Team conventions

[中文版 / Chinese version](CONTRIBUTING.zh.md). This English version translates the team's rules and adds
the pre-push check and CI introduced in October 2026.

## Environment

Follow the [README](README.md): use `uv sync --locked`, and create your local `.env` from
`backend/.env.example`. Commit `pyproject.toml` and `uv.lock`; never commit `.env` or `.venv`. Ignore rules
live in the root `.gitignore`. Files that are already tracked must be checked separately: an ignore rule
does not untrack them.

After changing dependencies, run `uv lock` in `backend/` and re-export `requirements.txt` with the command
printed at the top of that file, so the Docker image installs the same versions.

## Branches and pull requests

Create a `feat/<feature>`, `fix/<issue>` or `docs/<topic>` branch from `main`. When it is done, open a pull
request and ask a teammate to review it before merging. The PR description states the problem, the changed
behaviour, the affected endpoints and pages, how it was verified, and whether dependencies or configuration
must be updated.

```bash
git checkout main && git pull
git checkout -b feat/my-change
# ... work ...
python scripts/check_repo.py          # must print PASS
git add -A && git status              # read the list before committing
git commit -m "Explain what changed and why"
git push -u origin feat/my-change     # then open the pull request on GitHub
```

GitHub Actions runs the backend tests, the simulator and chat tests, and the safety check on every push
and pull request. Run the relevant checks locally as well and mention the results in the PR.

## Before every push

`python scripts/check_repo.py` must print PASS. It fails on API keys, passwords or tokens written as
literal values (including in README examples), `.env` files, runtime databases and keys, files over
50 MB, and shell scripts with Windows line endings. If a real secret was ever pushed, change it: removing
it from the latest version does not remove it from git history.

## API changes

1. Update `backend/app/` and its callers.
2. Update `backend/tests/` and run `uv run --locked pytest -q`.
3. Update the fields, SSE events and error semantics in `backend/API_DOCUMENTATION.md`.
4. In `backend/`, run `uv run --locked python -m scripts.export_openapi` and commit `docs/openapi.json`.
5. For breaking changes, describe the migration path in the PR. Do not silently change `delta`/`done` or field types.

OpenAPI and Markdown are updated in the same PR; after importing into Apipost, check the actual base URL.
Until there is a shared deployment, each member runs their own local service.

## Data and tests

`data/*.csv` are the seed and the regression baseline. Live data is written to MySQL through the admin
API, uploads, or whitelisted scheduled sync. `frontend/data.js` is a dynamic loader: do not overwrite it
and do not commit generated snapshots. `scripts.gen_snapshot` and `scripts.build_frontend_data` only
export the git-ignored `data/snapshots/data.snapshot.json`.

For streaming UI changes, run the mock tests in `tests/e2e`. `scripts.smoke_stream` and `smoke_live` call
the real workflow SSE and JSON endpoints and the real model API; run them manually when needed. Error
reports and screenshots must not contain keys.

Use the scripts in `backend/scripts` for maintenance, and Alembic migrations for schema changes. Database
changes follow the [data pipeline](docs/data_pipeline.md): after changing ORM/Pydantic models, generate and
review an Alembic migration, and update `schema.yaml`, OpenAPI and the lock file. Raw data, runtime files
and credentials never go into git. Production code must read from the database; CSV adapters are only for
regression tests and import baselines.

Live model evaluation uses a separate test database as described in the
[verification report](docs/live_model_verification.md) and consumes real API quota. Record first-run
failures and rate-limited reruns separately; never report a merged result as a single-run pass rate, and
never treat a passing test database as a finished deployment.

## Simulator, briefing demo and dashboard chat

```bash
python -m simulation.render_demo --days 14     # rebuilds demo/ and briefings/
python -m pytest -q tests/test_simulation.py tests/test_chat.py
```

CI rebuilds the demo and fails if the committed `demo/` or `briefings/` differ, so commit the rebuilt files
whenever you change `simulation/`.

## Notebooks

Keep notebooks small and move reusable code into modules. Strip outputs before committing
(`pip install nbstripout && nbstripout --install` once per clone), so diffs stay readable and no data or
keys leak through cell outputs. Use the project kernel described in the README (`uv add --dev ipykernel`).
