#!/bin/sh
set -eu

echo "--- docker compose ls"
docker compose ls || true
echo "--- docker ps"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
