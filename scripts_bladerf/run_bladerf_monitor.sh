#!/usr/bin/env bash
set -euo pipefail

# Helper to run GNSS-SDR in realtime with the BladeRF monitor config
# Usage: ./scripts_bladerf/run_bladerf_monitor.sh [path/to/config]

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${1:-${ROOT_DIR}/conf/RealTime_input/gnss-sdr_GPS_L1_bladeRF_monitor.conf}"

export VOLK_GENERIC=${VOLK_GENERIC:-1}

LOGDIR="/tmp/gnss-sdr-bladerf-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOGDIR"

echo "Using config: $CONFIG"
echo "Log dir: $LOGDIR"

GNSS_SDR_BIN="/usr/local/bin/gnss-sdr"
if [ ! -x "$GNSS_SDR_BIN" ]; then
  echo "gnss-sdr binary not found at $GNSS_SDR_BIN. Please install it using 'sudo apt install gnss-sdr'."
  exit 1
fi

echo "Starting gnss-sdr for BladeRF (press Ctrl-C to stop) ..."
# Explicitly turn on Bias-Tee on RX1 for the active antenna
echo "Enabling BladeRF Bias-Tee on RX1..."
bladeRF-cli -d "*:serial=0eecd0f37bd54ac8acd1aca9a37c080b" -e "set biastee rx1 on"
cd "$LOGDIR"
"$GNSS_SDR_BIN" --config_file="$CONFIG" --log_dir="$LOGDIR" -alsologtostderr

echo "gnss-sdr exited. Logs are in: $LOGDIR"
