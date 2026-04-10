#!/bin/sh
set -eu

echo "--- project root"
cd /srv/orchestrator-mvp
pwd
echo "--- compose files"
ls -1 docker-compose*.yml docker-compose*.yaml 2>/dev/null || true
echo "--- compose ls"
docker compose ls || true
echo "--- docker ps"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
echo "--- repo files"
ls -lah | head -n 60
