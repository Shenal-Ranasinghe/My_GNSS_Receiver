#!/usr/bin/env bash
set -euo pipefail

# Helper to run GNSS-SDR in realtime with the Pluto monitor config
# Usage: ./scripts/run_pluto_monitor.sh [path/to/config]

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${1:-${ROOT_DIR}/conf/RealTime_input/gnss-sdr_GPS_L1_plutosdr_monitor.conf}"

export VOLK_GENERIC=${VOLK_GENERIC:-1}

LOGDIR="/tmp/gnss-sdr-monitor-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOGDIR"

echo "Using config: $CONFIG"
echo "Log dir: $LOGDIR"

GNSS_SDR_BIN="$ROOT_DIR/build/src/main/gnss-sdr"
if [ ! -x "$GNSS_SDR_BIN" ]; then
  echo "gnss-sdr binary not found at $GNSS_SDR_BIN. Build first: cd $ROOT_DIR && mkdir -p build && cd build && cmake .. && make -j"
  exit 1
fi

echo "Starting gnss-sdr (press Ctrl-C to stop) ..."
cd "$LOGDIR"
"$GNSS_SDR_BIN" --config_file="$CONFIG" --log_dir="$LOGDIR" -alsologtostderr

echo "gnss-sdr exited. Logs are in: $LOGDIR" 
