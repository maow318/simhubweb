#!/bin/sh
set -eu

SIMHUB_USER="${SIMHUB_USER:-simhub}"
SIMHUB_DATA_DIR="${SIMHUB_DATA_DIR:-/data}"
DATABASE_PATH="${DATABASE:-/data/simhub.sqlite}"
DATABASE_DIR="$(dirname "$DATABASE_PATH")"

mkdir -p "$SIMHUB_DATA_DIR"
if [ "$DATABASE_DIR" != "." ]; then
    mkdir -p "$DATABASE_DIR"
fi

if [ "$(id -u)" = "0" ]; then
    chown -R "$SIMHUB_USER:$SIMHUB_USER" "$SIMHUB_DATA_DIR"
    if [ "$DATABASE_DIR" != "$SIMHUB_DATA_DIR" ] && [ "$DATABASE_DIR" != "." ]; then
        chown -R "$SIMHUB_USER:$SIMHUB_USER" "$DATABASE_DIR"
    fi
    chmod -R u+rwX,g+rwX "$SIMHUB_DATA_DIR"
    exec docker-drop-privileges "$SIMHUB_USER" "$@"
fi

exec "$@"
