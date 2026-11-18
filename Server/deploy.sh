#!/usr/bin/env bash
# Deploys this directory to the production API server (KOSA_경진대회_09).
# Usage: ROUNDUP_SSH_TARGET=user@223.130.130.1 Server/deploy.sh
# Optional: ROUNDUP_SSH_KEY, default ~/.ssh/roundup_ed25519.
set -euo pipefail

target="${ROUNDUP_SSH_TARGET:?Set ROUNDUP_SSH_TARGET to user@223.130.130.1}"
key="${ROUNDUP_SSH_KEY:-$HOME/.ssh/roundup_ed25519}"
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
release="r$(date -u +%Y%m%d%H%M%S)"
remote() { ssh -i "$key" -o BatchMode=yes -o ConnectTimeout=10 "$target" "$@"; }

remote "sudo install -d -m 750 /opt/roundup/releases/$release"
COPYFILE_DISABLE=1 tar --no-xattrs -C "$source_dir" \
  --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache \
  --exclude='*.env' --exclude=.env.example --exclude=tests -czf - . \
  | remote "sudo tar --warning=no-unknown-keyword -xzf - -C /opt/roundup/releases/$release"

remote "sudo bash -s -- $release" <<'REMOTE'
set -euo pipefail
root=/opt/roundup
dir="$root/releases/$1"
previous="$(readlink -f "$root/current")"
unit=/etc/systemd/system/roundup-api.service
install -m 600 "$previous/db.env" "$dir/db.env"
install -m 644 "$unit" "$dir/previous.service"
install -d -m 700 "$root/backups"
cd "$dir"
/usr/local/bin/uv sync --frozen --no-dev -q

run() {
  systemd-run --quiet --wait --pipe --collect \
    -p EnvironmentFile="$root/server.env" -p EnvironmentFile="$dir/db.env" \
    -p WorkingDirectory="$dir" "$@"
}

run "$dir/.venv/bin/python" -c '
import asyncio, os, asyncpg
async def main():
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "", 1)
    ssl = os.environ.get("DATABASE_SSLMODE", "verify-full") != "disable"
    db = await asyncpg.connect(url, ssl=ssl)
    print(await db.fetchval("select coalesce(json_agg(i), \x27[]\x27)::text from inquiries i"))
    await db.close()
asyncio.run(main())
' > "$root/backups/$1-inquiries.json"
chmod 600 "$root/backups/$1-inquiries.json"

run "$dir/.venv/bin/alembic" upgrade head
run "$dir/.venv/bin/python" seed.py

ln -sfn "$dir" "$root/current"
install -m 644 "$dir/roundup-api.service" "$unit"
systemctl daemon-reload
systemctl restart roundup-api

ready() {
  run "$dir/.venv/bin/python" -c '
import os, ssl, urllib.request
context = ssl._create_unverified_context()
request = urllib.request.Request("https://127.0.0.1:8787/health/ready", headers={"X-Roundup-Key": os.environ["ROUNDUP_API_KEY"]})
urllib.request.urlopen(request, context=context, timeout=5)
' 2>/dev/null
}

for _ in $(seq 1 30); do
  if ready; then
    echo "Deployed $1"
    exit 0
  fi
  sleep 1
done

echo "Health check failed; restoring the previous release" >&2
ln -sfn "$previous" "$root/current"
install -m 644 "$dir/previous.service" "$unit"
systemctl daemon-reload
systemctl restart roundup-api
exit 1
REMOTE
