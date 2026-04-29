#!/usr/bin/env python3
"""Rotate (truncate) the GNSS-SDR NMEA PVT file when it grows past a threshold.

This script truncates the file in-place so GNSS-SDR can continue writing to the same inode.

Usage: python3 scripts/rotate_nmea.py --file /path/to/gnss_sdr_pvt.nmea --max-mb 100
"""
import os
import time
import argparse


def keep_tail(path, keep_bytes):
    fd = os.open(path, os.O_RDWR)
    try:
        st = os.fstat(fd)
        size = st.st_size
        if size <= keep_bytes:
            return
        start = size - keep_bytes
        os.lseek(fd, start, os.SEEK_SET)
        tail = b''
        while len(tail) < keep_bytes:
            chunk = os.read(fd, keep_bytes - len(tail))
            if not chunk:
                break
            tail += chunk
        newline = tail.find(b'\n')
        if newline != -1:
            tail = tail[newline+1:]
        os.lseek(fd, 0, os.SEEK_SET)
        written = 0
        while written < len(tail):
            n = os.write(fd, tail[written:])
            if n <= 0:
                break
            written += n
        os.ftruncate(fd, len(tail))
    finally:
        os.close(fd)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--file', '-f', required=True, help='Path to NMEA file to monitor')
    p.add_argument('--max-mb', type=int, default=100, help='Maximum file size in MB before truncation (default: 100)')
    p.add_argument('--interval', type=int, default=10, help='Check interval seconds (default: 10)')
    args = p.parse_args()

    path = args.file
    max_bytes = args.max_mb * 1024 * 1024

    print(f'Monitoring {path}; rotating at {args.max_mb} MB')
    try:
        while True:
            if not os.path.exists(path):
                print(f'Waiting for file to appear: {path}')
                time.sleep(args.interval)
                continue
            try:
                st = os.stat(path)
            except FileNotFoundError:
                time.sleep(args.interval)
                continue
            if st.st_size > max_bytes:
                print(f"Rotating {path} (size {st.st_size} bytes)")
                try:
                    keep_tail(path, max_bytes)
                except Exception as e:
                    print('Failed to rotate:', e)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('Stopped')


if __name__ == '__main__':
    main()
