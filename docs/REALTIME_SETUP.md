**Realtime Pluto monitor — Quick setup**

- **Config:** `conf/RealTime_input/gnss-sdr_GPS_L1_plutosdr_monitor.conf` (uses `Ad936x_Custom_Signal_Source` by default)
- **Run helper script:** `scripts/run_pluto_monitor.sh`

Steps

- Ensure the ADALM-PLUTO is connected and reachable. If using USB Ethernet/gadget, set your host address to the same subnet (e.g., `192.168.2.x`) and keep Pluto at `192.168.2.1`.
- Verify device visibility:

```bash
iio_info
ping -c 2 192.168.2.1
```

- Build GNSS-SDR (if not already built):

```bash
cd /home/shenal-ranasinghe/GNSS_SDR/gnss-sdr
mkdir -p build && cd build
cmake .. -DENABLE_PLUTOSDR=ON
make -j$(nproc)
```

- Run the realtime monitor (uses `VOLK_GENERIC=1` by default to avoid some volk/gr-iio ABI issues):

```bash
cd /home/shenal-ranasinghe/GNSS_SDR/gnss-sdr
./scripts/run_pluto_monitor.sh
```

- While GNSS-SDR runs, NMEA PVT sentences are written to `/tmp/gnss_sdr_pvt.nmea` by default. You can monitor them:

```bash
tail -f /tmp/gnss_sdr_pvt.nmea
```

New utilities

- `scripts/monitor_dashboard.py` — a small matplotlib-based dashboard that reads the latest run directory under `/tmp/gnss-sdr-monitor-*`, parses GNSS-SDR logs for tracked PRNs and tails the `gnss_sdr_pvt.nmea` file to plot position on a simple lat/lon grid.
- `scripts/rotate_nmea.py` — background script to monitor the `gnss_sdr_pvt.nmea` file and truncate it in-place when it exceeds a configured size (keeps GNSS-SDR writing to the same file/inode while preventing unbounded growth).

Quick start

1) Start GNSS-SDR with the monitor config (from repo root):

```bash
./scripts/run_pluto_monitor.sh
```

This creates a directory like `/tmp/gnss-sdr-monitor-YYYYMMDD-HHMMSS` and writes logs and `gnss_sdr_pvt.nmea` inside it.

2) Start the rotation watcher in another terminal (adjust max size as needed):

```bash
# replace PATH with the actual log directory if you don't want auto-detection
python3 scripts/rotate_nmea.py --file /tmp/gnss-sdr-monitor-YYYYMMDD-HHMMSS/gnss_sdr_pvt.nmea --max-mb 50 &
```

3) Start the dashboard in another terminal. If you omit the directory it will pick the latest `/tmp/gnss-sdr-monitor-*`:

```bash
python3 scripts/monitor_dashboard.py /tmp/gnss-sdr-monitor-YYYYMMDD-HHMMSS
```

Notes

- The rotation script truncates the file in-place so GNSS-SDR continues writing to the same inode — this avoids breaking file handles.
- The dashboard is intentionally simple: it extracts PRN acquisition/tracking/loss messages from the GNSS-SDR log and plots latest GGA-based latitude/longitude on a plain grid (no external map tiles required). If you want a nicer web map later (Leaflet/folium), I can add an HTML-based dashboard.


Permissions / udev (optional)

If you prefer not to run as root and device access fails, create a udev rule for Pluto (example content):

```
# /etc/udev/rules.d/99-pluto.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="0456", ATTR{idProduct}=="b673", MODE:="0666"
```

Then reload udev rules:

```bash
sudo udevadm control --reload
sudo udevadm trigger
```

Next steps / Improvements

- If you want a systemd service to run the monitor on boot, tell me and I will create a unit file.
- If you prefer the `Plutosdr_Signal_Source` implementation instead, we can try rebuilding `gr-iio`/`volk` or run with debug symbols to root-cause the segfault.
