#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python3 start_nes_radar_server.py "$@"
