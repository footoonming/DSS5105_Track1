# Publishing this work to GitHub

The team already has a GitHub repository: **`jingweiluo557/DSS5105`**. It is **public**, and ThreadPilot
lives in its `threadpilot/` folder. The version on GitHub is older than the team's local copy: it has no
`docker-compose.yml` and no SQL agent. So the job is to bring the repository up to date with **one branch
and one pull request**, not to create a new repository.

This package mirrors the repository layout:

```
DSS5105/                      repository root
├── .github/workflows/threadpilot-tests.yml   CI: tests and safety check on every push and PR
├── .gitattributes            keeps shell scripts and generated demo files stable across Windows/macOS
├── README.md                 points to threadpilot/
└── threadpilot/              the project, cleaned and documented
```

---

## 0. Security first (do this before anything else)

1. **Change the MySQL root password** that appeared in the Windows example of README section 7.4 in the
   local copy. It was the live password from `.env`. It is not in the README currently on GitHub (checked
   2 October 2026), but the local copy was zipped and shared. Change it wherever else it is used too.
   The package's `README.zh.md` now uses placeholders.
2. **Revoke and replace the OpenAI key** that was in `backend/.env` inside the shared zip.
3. **Generate new** `MYSQL_APP_PASSWORD`, `MYSQL_AI_PASSWORD` and `DATA_API_TOKEN` for the same reason.
4. From now on, never zip, email or chat-send `.env` files. Share `.env.example`.
5. The repository is public. Check that the team and the course are happy with that. To make it private:
   Settings → General → Danger Zone → Change visibility, then add lecturers under Settings → Collaborators.

## 1. Pick the source copy

The person whose local ThreadPilot is the newest working version does the steps below, on their machine,
and needs push access to the repository.

* If their copy has **not changed** since the zip that was reviewed, use this package as it is (section 2).
* If it **has changed**, start from their copy and add the package's new files on top (section 4).

## 2. Update the repository on a branch

```bash
git clone https://github.com/jingweiluo557/DSS5105.git
cd DSS5105
git checkout -b chore/repo-ready
git rm -r -q threadpilot          # remove the old copy on this branch (history keeps it)
```

Copy the **contents** of the package's `DSS5105/` folder into the clone, including the hidden `.github`
folder and `.gitattributes`:

```bash
cp -R /path/to/package/DSS5105/. .                                   # macOS / Linux
```
```powershell
Copy-Item -Recurse -Force C:\path\to\package\DSS5105\* .              # Windows PowerShell
Test-Path .github, .gitattributes                                     # both must print True
```

## 3. Check, commit, push, open the pull request

```bash
cd threadpilot
python scripts/check_repo.py      # must end with PASS
cd ..
git add -A
git status                        # read the list: no .env, no runtime/, no .venv, no __pycache__
git commit -m "Prepare repository: English docs, CI, safety check, simulator and dashboard chat, ML model"
git push -u origin chore/repo-ready
```

On GitHub, open the pull request (a "Compare & pull request" button appears). The **Actions** tab runs
three jobs: the safety check, the backend tests, and the simulator/chat tests. Ask a teammate to review,
then merge.

After merging, everyone runs `git checkout main && git pull` and creates their own `.env` from
`.env.example`. Before each presentation, freeze the version:

```bash
git tag -a sprint1 -m "Sprint 1, 16 Oct 2026" && git push --tags
```

## 4. If the newest code is not the reviewed zip

Start from the newest copy (cloned and on a branch as in section 2, with that copy's files in
`threadpilot/`), then bring in from this package:

| Action | Files |
|---|---|
| Add | `threadpilot/simulation/`, `demo/`, `briefings/`, `ml/`, `prototypes/`, `scripts/check_repo.py`, `tests/conftest.py`, `tests/test_simulation.py`, `tests/test_chat.py`, `docs/chat_tools.md`, `docs/CODE_REVIEW.md`, `docs/DASHBOARD_REVIEW.md`, `docs/GITHUB_GUIDE.md`; repository root: `.github/`, `.gitattributes`, `README.md` |
| Rename, then replace | `README.md` → `README.zh.md` (and replace the real passwords in section 7.4 with placeholders); `CONTRIBUTING.md` → `CONTRIBUTING.zh.md`; then add the package's English `README.md` and `CONTRIBUTING.md` |
| Edit | `.gitignore`: add `data/live/`, `*.sqlite3`, `*.pem`, `.ipynb_checkpoints/`. `.env.example` and `backend/.env.example`: the `BUSINESS_NOW` comment and value. `backend/start.sh`: save with LF line endings |

Then run `python scripts/check_repo.py` and the tests from the README before committing.

## 5. Optional: let Claude Code do sections 2 and 3

Open the cloned `DSS5105` folder in Claude Code and paste:

```
Follow docs/GITHUB_GUIDE.md from the package at <PATH TO PACKAGE>/DSS5105/threadpilot/docs/.
Work on a new branch chore/repo-ready. Never print or commit the contents of any .env file.
Stop and show me `python threadpilot/scripts/check_repo.py` and `git status` before committing,
and ask before pushing.
```

---

## What was verified, and what was not

Verified in a clean Linux environment, on a fresh `git clone` of the prepared repository:

* `python scripts/check_repo.py`: PASS (180 files, also after running the tests)
* Backend tests with `uv sync --locked --group dev` and `uv run --locked pytest -q`: 70 passed, 1 skipped (the MySQL integration test, which needs `TEST_MYSQL_URL`)
* Simulator, briefing and chat tests: 50 passed
* `python -m simulation.render_demo --days 14` reproduces the committed `demo/` and `briefings/` byte for byte
* The workflow file parses as valid YAML

Not verified: MySQL provisioning and seeding, Docker Compose, the Windows/PowerShell commands, the ML
package's `run_demo.py`, and the GitHub Actions run itself (it first runs when you push).

## Corrections to earlier advice

* An earlier guide said to stop ignoring `data/raw/`. That was wrong: the seed command loads the committed
  `data/*.csv`, and `data/raw/` is only for optional file imports and sync, so it should stay ignored.
* An earlier guide described creating a new repository. The team already has one; use it.
