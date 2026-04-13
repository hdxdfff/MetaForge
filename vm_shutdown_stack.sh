#!/bin/sh
set -eu

echo "--- compose files"
find /home/codex -maxdepth 3 \( -name 'compose.yml' -o -name 'compose.yaml' -o -name 'docker-compose.yml' -o -name 'docker-compose.yaml' \) -print

echo "--- docker compose ls"
docker compose ls || true

cid="$(docker ps -q --filter name=orchestrator-mvp-orchestrator-1 | head -n 1)"
if [ -z "$cid" ]; then
  echo "orchestrator container not running"
  exit 0
fi

project="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$cid" 2>/dev/null || true)"
echo "--- target"
echo "cid=$cid"
echo "project=$project"
workdir=""
for candidate in /home/codex /home/codex/orchestrator-mvp /home/codex/dev/orchestrator-mvp /home/codex/dev/c-smoke; do
  if [ -f "$candidate/compose.yml" ] || [ -f "$candidate/compose.yaml" ] || [ -f "$candidate/docker-compose.yml" ] || [ -f "$candidate/docker-compose.yaml" ]; then
    workdir="$candidate"
    break
  fi
done
echo "workdir=$workdir"

if [ -n "$workdir" ]; then
  cd "$workdir"
  echo "--- docker compose down"
  docker compose down
elif [ -d /srv/orchestrator-mvp ]; then
  cd /srv/orchestrator-mvp
  echo "--- docker compose down (srv/orchestrator-mvp)"
  docker compose -f docker-compose.control-entry.yml -f docker-compose.control-entry.override.yml -f docker-compose.yml -f docker-compose.override.yml down
else
  echo "--- fallback docker stop"
  docker stop "$cid"
fi
