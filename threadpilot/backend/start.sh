#!/bin/sh
# Local development launcher; arguments are optional --reload and --port NUMBER.
set -eu
cd "$(dirname "$0")"
command -v uv >/dev/null 2>&1 || { echo 'Install uv before starting ThreadPilot.' >&2; exit 1; }
[ -f .env ] || { echo 'Create backend/.env and initialize local MySQL first. See README section 7.' >&2; exit 1; }
port=8000
reload=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --reload) reload=true; shift ;;
        --port) [ "$#" -ge 2 ] || { echo 'Missing port' >&2; exit 2; }; port="$2"; shift 2 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
case "$port" in ''|*[!0-9]*) echo 'Invalid port' >&2; exit 2 ;; esac
[ "$port" -ge 1 ] && [ "$port" -le 65535 ] || { echo 'Port must be 1-65535' >&2; exit 2; }
set -- uv run --locked uvicorn app.main:app --host 127.0.0.1 --port "$port" --workers 1
if [ "$reload" = true ]; then set -- "$@" --reload; fi
exec "$@"
