#!/usr/bin/env bash
# Deploys this directory to the production API server (NCP sub-account scnu).
# Usage: Server/deploy.sh
# Optional: ROUNDUP_SSH_TARGET, default deploy@211.233.193.216.
# Optional: ROUNDUP_SSH_KEY, default ~/.ssh/gongbang-prod.
# Optional: AGENT_WORKER=1 installs the agent worker unit; without it an enabled unit follows the release.
set -euo pipefail

target="${ROUNDUP_SSH_TARGET:-deploy@211.233.193.216}"
key="${ROUNDUP_SSH_KEY:-$HOME/.ssh/gongbang-prod}"
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
release="r$(date -u +%Y%m%d%H%M%S)"
remote() {
  ssh -i "$key" -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$target" "$@"
}

remote "sudo install -d -o gongbang -g gongbang -m 750 /opt/gongbang/releases/$release"
COPYFILE_DISABLE=1 tar --no-xattrs -C "$source_dir" \
  --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache \
  --exclude='*.env' --exclude=.env.example --exclude=tests -czf - . \
  | remote "sudo tar --warning=no-unknown-keyword -xzf - -C /opt/gongbang/releases/$release"

remote "sudo bash -s -- $release" <<'REMOTE'
set -euo pipefail
root=/opt/gongbang
dir="$root/releases/$1"
previous="$(readlink -f "$root/current")"
unit=/etc/systemd/system/roundup-api.service
chown -R gongbang:gongbang "$dir"
install -m 644 "$unit" "$dir/previous.service"
install -d -m 700 -o root -g root "$root/backups"
cd /tmp
sudo -u gongbang -H env UV_PYTHON_PREFERENCE=only-system bash -c "cd '$dir' && /usr/local/bin/uv sync --frozen --no-dev -q"

run() {
  systemd-run --quiet --wait --pipe --collect --uid=gongbang --gid=gongbang \
    -p EnvironmentFile="$root/server.env" -p WorkingDirectory="$dir" "$@"
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

# Restart=always would start a dying worker from a release nobody has checked yet, so an enabled worker
# stands still until the health check; a failed deploy leaves it stopped.
worker_waits=
if systemctl is-enabled --quiet roundup-agent 2>/dev/null; then
  systemctl stop roundup-agent
  worker_waits=1
fi

ln -sfn "$dir" "$root/current"
install -m 644 "$dir/roundup-api.service" "$unit"
# Collector units are refreshed only where an operator installed them; a first deploy changes nothing.
if [ -f /etc/systemd/system/collectors.timer ]; then
  install -m 644 "$dir/collectors.service" "$dir/collectors.timer" /etc/systemd/system/
fi
systemctl daemon-reload
systemctl restart roundup-api

ready() {
  run "$dir/.venv/bin/python" -c '
import os, urllib.request
request = urllib.request.Request("http://127.0.0.1:8000/health/ready", headers={"X-Roundup-Key": os.environ["ROUNDUP_API_KEY"]})
urllib.request.urlopen(request, timeout=5)
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
if [ -n "$worker_waits" ]; then
  echo "The agent worker stays stopped; start it with: systemctl start roundup-agent" >&2
fi
exit 1
REMOTE

# Only a healthy release gets here. AGENT_WORKER=1 installs the worker; without it a worker that is already
# enabled restarts on the new code, and a host without one is left alone.
if [ "${AGENT_WORKER:-}" = 1 ]; then worker=install; else worker=restart; fi
remote "sudo bash -s -- $release $worker" <<'WORKER'
set -euo pipefail
if [ "$2" = install ]; then
  unit=/etc/systemd/system/roundup-agent.service
  install -m 644 "/opt/gongbang/releases/$1/deploy/roundup-agent.service" "$unit"
  systemctl daemon-reload
  systemctl enable --quiet roundup-agent
elif ! systemctl is-enabled --quiet roundup-agent 2>/dev/null; then
  exit 0
fi
systemctl restart roundup-agent
# A worker that dies on import shows within seconds; is-active alone would miss it.
for _ in 1 2 3; do
  sleep 1
  if ! systemctl is-active --quiet roundup-agent; then
    echo "The agent worker did not stay up; see: journalctl -u roundup-agent" >&2
    exit 1
  fi
done
echo "Agent worker running"
WORKER
