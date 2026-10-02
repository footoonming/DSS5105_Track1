"""Pre-push safety check for the ThreadPilot repository. Standard library only.

Run it from the threadpilot/ folder before every commit you intend to push:

    python scripts/check_repo.py

Inside a git repository it checks exactly the files git would commit (tracked plus untracked,
not ignored). Outside git it walks the folder and skips the usual ignored paths.

It fails (exit code 1) on:
  * secrets: API keys, private keys, passwords or tokens written as literal values, database URLs
    with a password in them. Values are never printed, only file, line and kind.
  * files that must never be committed: .env, .venv, backend/runtime contents, *.pem, *.sqlite3,
    MySQL data files, __pycache__
  * files larger than 50 MB (GitHub rejects files over 100 MB)
  * shell scripts with Windows line endings (they break on macOS and Linux)
  * missing files a fresh clone needs
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_MB = 50
REQUIRED = ["README.md", ".gitignore", ".env.example", "backend/.env.example", "backend/pyproject.toml",
            "backend/uv.lock", "data/orders.csv", "data/production_log.csv", "data/workshops.csv"]
FORBIDDEN = [
    (re.compile(r"(^|/)\.env$"), "a real .env file (only .env.example belongs in git)"),
    (re.compile(r"(^|/)\.env\.(?!example$)[^/]+$"), "an .env variant"),
    (re.compile(r"(^|/)\.venv/"), "a virtual environment"),
    (re.compile(r"(^|/)__pycache__/|\.py[co]$"), "compiled Python"),
    (re.compile(r"^backend/runtime/(?!\.gitkeep$)"), "runtime data (databases, MySQL files, keys)"),
    (re.compile(r"\.(pem|key|p12|pfx)$"), "a key or certificate file"),
    (re.compile(r"\.(sqlite3?|db|ibd)$"), "a database file"),
]
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", "runtime", "test-results"}
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".xlsx", ".pkl", ".pdf", ".zip", ".ico", ".woff", ".woff2"}

# --- secret detectors: (pattern, kind). Group "v" is the value that must not be a placeholder.
SECRET_RULES = [
    (re.compile(r"(?P<v>sk-(?:proj-)?[A-Za-z0-9_\-]{20,})"), "API key (sk-...)"),
    (re.compile(r"(?P<v>-----BEGIN [A-Z ]*PRIVATE KEY-----)"), "private key block"),
    (re.compile(r"(?P<v>gh[pousr]_[A-Za-z0-9]{30,})"), "GitHub token"),
    # NAME = 'value' / NAME: "value" / $env:NAME = 'value' with a secret-looking name
    (re.compile(r"(?i)\b[\w$:]*(?:password|passwd|secret|token|api_key|apikey)\w*\s*[:=]\s*(?P<q>['\"])(?P<v>[^'\"\n]{6,})(?P=q)"),
     "password/token written as a literal"),
    # dotenv-style lines: NAME=value (in any committed file, e.g. README code blocks or .env.example)
    (re.compile(r"(?m)^\s*(?:export\s+)?[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY)[A-Z0-9_]*\s*=\s*(?P<v>[^\s#'\"]{6,})"),
     "password/token in an env-style line"),
    (re.compile(r"[a-z+]+://[^:/\s@]+:(?P<v>[^@\s/]{6,})@"), "database URL with an embedded password"),
]
PLACEHOLDER = re.compile(
    r"(?i)^(?:replace|change|your|example|placeholder|dummy|fake|test|sample|xxx|\*{3}|<|\$|\{|%|none|null|"
    r"secret_?here|password_?here|token_?here|only_for|never|redacted)|<[^>]*>|\$\{|\$\(|\{\{|\.\.\.|…|"
    r"^(?:root_password|password|passwords?\[|settings\.|os\.environ|getenv|secrets\.)")


def files_to_check() -> tuple[list[str], bool]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8", "replace")
        return sorted(p for p in out.split("\0") if p and (ROOT / p).exists()), True
    except Exception:
        found = []
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and not (set(rel.split("/")[:-1]) & SKIP_DIRS) and not rel.startswith("data/raw/"):
                found.append(rel)
        return sorted(found), False


def is_placeholder(value: str, path: str) -> bool:
    if PLACEHOLDER.search(value) or re.search(r"[^\x00-\x7f]", value):  # e.g. a description written in Chinese
        return True
    if "/tests/" in f"/{path}" and re.search(r"(?i)test|only_for|never|isolat|dummy|fake", value):
        return True  # obviously fake values in test fixtures
    return False


def main() -> int:
    paths, in_git = files_to_check()
    problems: list[str] = []
    warnings: list[str] = []
    for rel in paths:
        for rx, why in FORBIDDEN:
            if rx.search(rel):
                problems.append(f"{rel}: {why} must not be committed")
                break
        p = ROOT / rel
        size_mb = p.stat().st_size / 1e6
        if size_mb > MAX_MB:
            problems.append(f"{rel}: {size_mb:.0f} MB is too large for git (use Git LFS, DVC or a shared drive)")
        elif size_mb > 10:
            warnings.append(f"{rel}: {size_mb:.0f} MB; consider keeping large data out of git")
        if p.suffix.lower() in BINARY or size_mb > 5:
            continue
        raw = p.read_bytes()
        if b"\0" in raw[:4096]:
            continue
        if rel.endswith(".sh") and b"\r\n" in raw:
            problems.append(f"{rel}: Windows line endings break shell scripts on macOS/Linux")
        text = raw.decode("utf-8", "replace")
        for n, line in enumerate(text.splitlines(), 1):
            for rx, kind in SECRET_RULES:
                if kind.endswith("env-style line") and rel.endswith(".py"):
                    continue  # Python code reads settings; literal values are caught by the rule above
                for m in rx.finditer(line):
                    v = m.group("v")
                    if kind.startswith(("API key", "private key", "GitHub")) or not is_placeholder(v, rel):
                        problems.append(f"{rel}:{n}: {kind} (value hidden, {len(v)} characters)")
    for req in REQUIRED:
        if not (ROOT / req).exists() or (in_git and req not in paths):
            problems.append(f"{req}: missing (a fresh clone needs it)")

    mode = "files git would commit" if in_git else "folder contents (not a git repository yet)"
    print(f"Checked {len(paths)} {mode} in {ROOT.name}/")
    for w in warnings:
        print(f"  WARN  {w}")
    for pr in problems:
        print(f"  FAIL  {pr}")
    if problems:
        print(f"\n{len(problems)} problem(s). Fix them before pushing. If a real secret was ever pushed, "
              "change it (rotate) - deleting it from the latest version does not remove it from git history.")
        return 1
    print("PASS: no secrets, forbidden files, oversized files or broken line endings found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
