#!/usr/bin/env python3
"""Real-time monitor dashboard for GNSS-SDR logs.

Shows tracked PRNs and plots the latest PVT position on a simple lat/lon grid.

Usage: python3 scripts/monitor_dashboard.py [log_dir]
If no log_dir is provided, the script picks the most recent /tmp/gnss-sdr-monitor-* directory.
"""
import getpass
import os
import re
import sys
import time
import threading
import subprocess
from collections import defaultdict, deque

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None
    print("matplotlib not found. Will run in console mode only.")


ACQ_RE = re.compile(r"Successful acquisition.*for satellite .*?(?:G |GPS PRN )?(\d+)")
TRACK_START_RE = re.compile(r"Tracking of .* started .* for satellite .*?(?:G |GPS PRN )?(\d+)")
PULLIN_RE = re.compile(r"Pull-in: .*?for satellite .*?(?:G |GPS PRN )?(\d+)")
LOSS_RE = re.compile(r"Loss of lock .* satellite .*?(?:G |GPS PRN )?(\d+)")


def find_latest_logdir():
    prefix = "/tmp/gnss-sdr-bladerf-"
    dirs = [d for d in os.listdir("/tmp") if d.startswith("gnss-sdr-bladerf-")]
    if not dirs:
        return None
    dirs = [os.path.join("/tmp", d) for d in dirs]
    dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return dirs[0]


def follow_file(path, callback, stop_event):
    # Robust file follower: reopens if file rotated or truncated.
    # This will block until the file exists, then follow new lines.
    while not stop_event.is_set():
        try:
            with open(path, "r", errors="ignore") as f:
                try:
                    inode = os.fstat(f.fileno()).st_ino
                except Exception:
                    inode = None
                buf = ""
                while not stop_event.is_set():
                    line = f.readline()
                    if line:
                        buf += line
                        if buf.endswith('\n'):
                            callback(buf.rstrip('\n'))
                            buf = ""
                        continue
                    # no new line; check for rotation/truncation
                    try:
                        st = os.stat(path)
                        if inode is not None and st.st_ino != inode:
                            # file rotated; break to reopen
                            break
                        if st.st_size < f.tell():
                            # truncated
                            f.seek(0)
                            buf = ""
                    except FileNotFoundError:
                        break
                    time.sleep(0.2)
        except FileNotFoundError:
            time.sleep(0.5)
            continue


class Dashboard:
    def __init__(self, logdir):
        self.logdir = logdir
        self.logfile = None
        self.nmea_file = None
        self.gpx_file = None
        self.acquired = set()
        self.tracking = set()
        self.locked = set()
        self.lost = set()
        self.prn_history = defaultdict(lambda: deque(maxlen=10))
        self.pos = None
        self.iio_overflow_count = 0
        self.last_overflow_time = None
        self.lock = threading.Lock()
        self.last_log_time = None
        self.log_inode = None
        if logdir:
            symlink_path = os.path.join(logdir, 'gnss-sdr.INFO')
            if os.path.islink(symlink_path):
                target = os.readlink(symlink_path)
                if not os.path.isabs(target):
                    target = os.path.join(logdir, target)
                if os.path.exists(target):
                    self.logfile = target
            if not self.logfile:
                logfiles = []
                for f in os.listdir(logdir):
                    path = os.path.join(logdir, f)
                    if os.path.isfile(path) and '.log' in f:
                        logfiles.append(path)
                logfiles.sort(key=os.path.getmtime, reverse=True)
                self.logfile = logfiles[0] if logfiles else None
            nmea = os.path.join(logdir, 'gnss_sdr_pvt.nmea')
            if os.path.exists(nmea):
                self.nmea_file = nmea
            gpx_candidates = [os.path.join(logdir, f) for f in os.listdir(logdir) if f.endswith('.gpx') and f.startswith('pvt_')]
            if gpx_candidates:
                gpx_candidates.sort(key=os.path.getmtime, reverse=True)
                self.gpx_file = gpx_candidates[0]
            # record logfile inode and mtime if available
            if self.logfile and os.path.exists(self.logfile):
                try:
                    st = os.stat(self.logfile)
                    self.log_inode = st.st_ino
                    self.last_log_time = st.st_mtime
                except Exception:
                    pass

    def process_log_line(self, line):
        # detect IIO overflow warnings
        if 'overflow' in line.lower():
            with self.lock:
                self.iio_overflow_count += 1
                self.last_overflow_time = time.time()
            # continue processing other events too
        # detect a new GNSS-SDR run / flowgraph start and reset state
        if 'Log file created' in line or 'Flowgraph connected' in line or 'Flowgraph started' in line:
            with self.lock:
                self.acquired.clear()
                self.tracking.clear()
                self.locked.clear()
                self.lost.clear()
                self.prn_history.clear()
                self.pos = None
                self.iio_overflow_count = 0
                self.last_overflow_time = None
            return
        # update last activity time
        try:
            self.last_log_time = time.time()
        except Exception:
            pass
        
        p = PULLIN_RE.search(line)
        if p:
            prn = p.group(1)
            with self.lock:
                self.locked.add(prn)
                self.tracking.add(prn)
                self.acquired.discard(prn)
                self.lost.discard(prn)
                self.prn_history[prn].append(('lock', time.time()))
            return
        a = ACQ_RE.search(line)
        if a:
            prn = a.group(1)
            with self.lock:
                if prn not in self.tracking and prn not in self.locked:
                    self.acquired.add(prn)
                self.prn_history[prn].append(('acq', time.time()))
            return
        t = TRACK_START_RE.search(line)
        if t:
            prn = t.group(1)
            with self.lock:
                self.tracking.add(prn)
                self.acquired.discard(prn)
                self.lost.discard(prn)
                self.prn_history[prn].append(('trk', time.time()))
            return
        l = LOSS_RE.search(line)
        if l:
            prn = l.group(1)
            with self.lock:
                self.tracking.discard(prn)
                self.locked.discard(prn)
                self.acquired.discard(prn)
                self.lost.add(prn)
                self.prn_history[prn].append(('loss', time.time()))
            return

    def process_nmea_line(self, line):
        # quick GGA parser: $--GGA,hhmmss.ss,lat,NS,lon,EW,fix, ...
        if not line.startswith('$'):
            return
        parts = line.split(',')
        if len(parts) < 6:
            return
        if parts[0].endswith('GGA'):
            try:
                lat_raw = parts[2]
                lat_dir = parts[3]
                lon_raw = parts[4]
                lon_dir = parts[5]
                if lat_raw and lon_raw:
                    lat = float(lat_raw[:2]) + float(lat_raw[2:]) / 60.0
                    if lat_dir == 'S':
                        lat = -lat
                    lon = float(lon_raw[:3]) + float(lon_raw[3:]) / 60.0
                    if lon_dir == 'W':
                        lon = -lon
                    with self.lock:
                        self.pos = (lat, lon)
            except Exception:
                pass

    def process_gpx_file(self):
        if not self.gpx_file:
            return
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(self.gpx_file)
            root = tree.getroot()
            namespace = {'gpx': 'http://www.topografix.com/GPX/1/1'}
            trkpts = root.findall('.//gpx:trkpt', namespace)
            if not trkpts:
                return
            last = trkpts[-1]
            lat = float(last.attrib['lat'])
            lon = float(last.attrib['lon'])
            with self.lock:
                self.pos = (lat, lon)
        except Exception:
            pass

    def start(self):
        stop_ev = threading.Event()
        threads = []
        if self.logfile:
            print('Monitoring log file:', self.logfile)
            t = threading.Thread(target=follow_file, args=(self.logfile, self.process_log_line, stop_ev), daemon=True)
            t.start(); threads.append(t)
        else:
            print('No log file found in', self.logdir)
        if self.nmea_file:
            print('Monitoring NMEA file:', self.nmea_file)
            t2 = threading.Thread(target=follow_file, args=(self.nmea_file, self.process_nmea_line, stop_ev), daemon=True)
            t2.start(); threads.append(t2)
        else:
            print('No NMEA file found in', self.logdir)
        if self.gpx_file:
            print('Using GPX fallback:', self.gpx_file)
            self.process_gpx_file()

        # record logfile inode and mtime if available
        if self.logfile and os.path.exists(self.logfile):
            try:
                st = os.stat(self.logfile)
                self.log_inode = st.st_ino
                self.last_log_time = st.st_mtime
            except Exception:
                pass

        # start plotting (if available) otherwise fall back to console output
        console_mode = False
        if plt is None:
            console_mode = True
        else:
            try:
                print('matplotlib backend:', plt.get_backend(), 'DISPLAY=', os.environ.get('DISPLAY'))
                plt.ion()
                fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10,5))
                ax1.set_title('Tracked PRNs')
                ax1.axis('off')
                ax2.set_title('Position (lat/lon)')
                ax2.set_xlabel('Longitude'); ax2.set_ylabel('Latitude')
                ax2.set_xlim(-180, 180); ax2.set_ylim(-90, 90)

                # manual clear keybinding: press 'c' to clear all state
                def _on_key(event):
                    try:
                        if event.key and event.key.lower() == 'c':
                            with self.lock:
                                self.acquired.clear()
                                self.tracking.clear()
                                self.locked.clear()
                                self.lost.clear()
                                self.prn_history.clear()
                                self.pos = None
                                self.iio_overflow_count = 0
                                self.last_overflow_time = None
                            print('Manual clear: dashboard state reset (keypress)')
                    except Exception:
                        pass

                fig.canvas.mpl_connect('key_press_event', _on_key)

            except Exception as e:
                print('GUI unavailable, falling back to console mode:', e)
                console_mode = True
            else:
                print('GUI initialized, showing plot window (check your display).')

        try:
            while True:
                if self.gpx_file:
                    self.process_gpx_file()
                with self.lock:
                    locked = sorted(self.locked, key=int)
                    tracking = sorted(self.tracking, key=int)
                    acquired = sorted(self.acquired, key=int)
                    lost = sorted(self.lost, key=int)
                    pos = self.pos
                ax1.clear(); ax1.axis('off'); ax1.set_title('Satellite Status')
                status_columns = [
                    ('Tracking', tracking),
                    ('Locked', locked),
                    ('Acquired', acquired),
                    ('Lost', lost),
                ]

                # helper to format timestamps
                def _fmt_ts(ts):
                    try:
                        return time.strftime('%H:%M:%S', time.localtime(ts))
                    except Exception:
                        return '--'

                # compute last event time per status by scanning prn_history
                def _last_time_for(events):
                    tmax = 0
                    for hist in self.prn_history.values():
                        for ev, ts in hist:
                            if ev in events and ts > tmax:
                                tmax = ts
                    return tmax if tmax else None

                ts_tracking = _last_time_for(('trk',))
                ts_locked = _last_time_for(('lock',))
                ts_acquired = _last_time_for(('acq',))
                ts_lost = _last_time_for(('loss',))

                overflow_count = self.iio_overflow_count
                last_overflow = self.last_overflow_time

                max_rows = max((len(prns) for _, prns in status_columns), default=0)
                header = ''.join(f'{name:<12}' for name, _ in status_columns)
                ts_row = ''.join(f'{val:<12}' for val in [
                    _fmt_ts(ts_tracking), _fmt_ts(ts_locked), _fmt_ts(ts_acquired), _fmt_ts(ts_lost)
                ])
                rows = [header, ts_row, ''.join('-' * 12 for _ in status_columns)]
                for i in range(max_rows):
                    row = []
                    for _, prns in status_columns:
                        row.append(prns[i] if i < len(prns) else '')
                    rows.append(''.join(f'{item:<12}' for item in row))
                if max_rows == 0:
                    rows.append('No satellites tracked yet'.ljust(12 * len(status_columns)))

                if console_mode:
                    # print a compact console status
                    print('\n' + '\n'.join(rows))
                    print(f'IIO overflows: {overflow_count}  last: {_fmt_ts(last_overflow) if last_overflow else "--"}')
                    if pos:
                        print(f'Position: {pos[0]:.6f}, {pos[1]:.6f}')
                    else:
                        print('Position: No fix yet')
                    time.sleep(1.0)
                    continue

                ax1.clear(); ax1.axis('off'); ax1.set_title('Satellite Status')
                ax1.text(0, 1, '\n'.join(rows), va='top', family='monospace')

                ax2.clear(); ax2.set_title('Position (lat/lon)'); ax2.set_xlabel('Longitude'); ax2.set_ylabel('Latitude')
                ax2.set_xlim(-180, 180); ax2.set_ylim(-90, 90)
                ax2.grid(True, linestyle=':')
                if pos:
                    ax2.plot(pos[1], pos[0], 'ro')
                    ax2.text(pos[1], pos[0], f'  {pos[0]:.5f},{pos[1]:.5f}')
                else:
                    ax2.text(0, 0, 'No position fix yet', ha='center', va='center', fontsize=12)
                # display overflow hint
                ax2.text(0.01, 0.99, f'Overflows: {overflow_count}', transform=ax2.transAxes, va='top', fontsize=8)
                plt.pause(1.0)
        except KeyboardInterrupt:
            stop_ev.set()
            print('Stopped')


def main():
    logdir = None
    if len(sys.argv) > 1:
        logdir = sys.argv[1]
    else:
        logdir = find_latest_logdir()

    # Wait for the directory to exist (friendly waiting)
    if logdir:
        print('Using log dir:', logdir)
        if not os.path.exists(logdir):
            print(f'Waiting for directory {logdir} to appear... (start gnss-sdr)')
            try:
                while not os.path.exists(logdir):
                    time.sleep(2)
            except KeyboardInterrupt:
                print('Interrupted while waiting for log directory. Exiting.')
                sys.exit(1)
    else:
        print('No GNSS-SDR run directory provided; waiting for /tmp/gnss-sdr-bladerf-* to appear...')
        try:
            while True:
                logdir = find_latest_logdir()
                if logdir and os.path.exists(logdir):
                    print('Found run directory:', logdir)
                    break
                time.sleep(2)
        except KeyboardInterrupt:
            print('Interrupted while waiting for run directory. Exiting.')
            sys.exit(1)

    dash = Dashboard(logdir)

    # Wait for at least one log file or the NMEA file to appear
    try:
        waited = 0
        while True:
            # detect log files
            possible_logs = [os.path.join(logdir, f) for f in os.listdir(logdir) if f.endswith('.log')]
            nmea_guess = os.path.join(logdir, 'gnss_sdr_pvt.nmea')
            if possible_logs:
                dash.logfile = possible_logs[0]
            if os.path.exists(nmea_guess):
                dash.nmea_file = nmea_guess
            if dash.logfile or dash.nmea_file:
                break
            if waited % 5 == 0:
                print('Waiting for GNSS-SDR log or NMEA file to appear in', logdir)
            time.sleep(2)
            waited += 1
    except KeyboardInterrupt:
        print('Interrupted while waiting for log/NMEA files. Exiting.')
        sys.exit(1)

    print('Starting dashboard; logfile=', dash.logfile, 'nmea=', dash.nmea_file)
    dash.start()


if __name__ == '__main__':
    main()
