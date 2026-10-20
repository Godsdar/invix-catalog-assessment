#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose -f compose.yaml -f compose.tunnel.yaml --profile telegram down
