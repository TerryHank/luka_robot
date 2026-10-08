#!/usr/bin/env bash
set -euo pipefail
exec sudo -n systemctl start luka-ws-moss.service
