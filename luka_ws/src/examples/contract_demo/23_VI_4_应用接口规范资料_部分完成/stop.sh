#!/usr/bin/env bash
set -eo pipefail
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/demo.sh" --stop
