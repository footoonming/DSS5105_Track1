# ThreadPilot

[中文说明](README.zh.md)

This folder is the ThreadPilot project. **The full documentation is in the [repository README](../README.md)**:
what it does, quick start, configuration, keeping the data current from Excel, the API, tests, and how to share it.

The commands used most, run from this folder:

```bash
python -m simulation.render_demo --days 14      # rebuild the demo page, then open demo/briefing_demo.html
docker compose up --build -d                    # the full system (create .env first: see the repository README)
docker compose run --rm backend python -m scripts.init_db --skip-migrate --seed-existing
python -m pytest -q tests/                      # simulator, prediction, dashboard and chat tests
python scripts/check_repo.py                    # before every push
```
