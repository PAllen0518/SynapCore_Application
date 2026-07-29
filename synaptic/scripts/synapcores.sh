#!/usr/bin/env bash
# Lifecycle helper for the local SynapCores CE dependency.
#
#   scripts/synapcores.sh up       start (or resume) the container
#   scripts/synapcores.sh creds    print the first-boot admin credentials
#   scripts/synapcores.sh status   health + resource usage
#   scripts/synapcores.sh stop     stop (keeps data volume)
#   scripts/synapcores.sh down     stop + remove container (keeps data volume)
#
# Uses podman if present, else docker. The container is CPU-bound (it runs an
# embedded LLM on CPU) and uses several GB of RAM, so stop it when idle.
set -euo pipefail

ENGINE="$(command -v podman || command -v docker)"
COMPOSE="$(dirname "$0")/../docker-compose.yml"
NAME="synapcores"

case "${1:-}" in
  up)
    : "${AIDB_JWT_SECRET:=$(openssl rand -base64 32 2>/dev/null || echo dev-secret)}"
    export AIDB_JWT_SECRET
    "$ENGINE" compose -f "$COMPOSE" up -d
    echo "waiting for health..."
    for _ in $(seq 1 30); do
      if curl -fsS -m 4 http://localhost:8090/health >/dev/null 2>&1; then
        echo "healthy at http://localhost:8090"; break
      fi
      sleep 2
    done
    ;;
  creds)
    "$ENGINE" logs "$NAME" 2>&1 | grep -A 12 FIRST-BOOT || \
      echo "no FIRST-BOOT block in logs (already consumed?)"
    ;;
  status)
    curl -fsS -m 4 http://localhost:8090/health || true; echo
    "$ENGINE" stats --no-stream "$NAME" 2>/dev/null || true
    ;;
  stop)  "$ENGINE" stop "$NAME" ;;
  down)  "$ENGINE" compose -f "$COMPOSE" down ;;
  *) sed -n '2,12p' "$0"; exit 1 ;;
esac
