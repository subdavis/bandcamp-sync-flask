#!/usr/bin/env python
"""
Container-friendly bandcampsync runner.

Takes cookies as a direct string argument (no temp files needed).
bandcampsync uses curl_cffi directly for TLS fingerprinting.
"""

import sys
import argparse
from pathlib import Path

from bandcampsync import version, do_sync
from bandcampsync.logger import get_logger


log = get_logger('sync_runner')


def main():
    parser = argparse.ArgumentParser(
        prog='sync_runner',
        description='Container-friendly bandcampsync runner that accepts cookies directly',
    )
    parser.add_argument('-v', '--version', action='store_true',
        help='Displays the bandcampsync version and exits')
    parser.add_argument('-C', '--cookies-string', required=True,
        help='Cookies string directly (not a file path)')
    parser.add_argument('-d', '--directory', required=True,
        help='Path to the directory to download media to')
    parser.add_argument('-I', '--ignore-file', default='',
        help='Path to the ignore file')
    parser.add_argument('-i', '--ignore', default='',
        help='A space-delimited list of patterns matching artists to bypass')
    parser.add_argument('-f', '--format', default='flac',
        help='Media format to download, defaults to "flac"')
    parser.add_argument('-t', '--temp-dir', default='',
        help='Path to use for temporary downloads')
    parser.add_argument('-n', '--notify-url', default='',
        help='URL to notify with a GET request when any new downloads have completed')
    
    args = parser.parse_args()
    
    if args.version:
        print(f'BandcampSync version: {version}', file=sys.stdout)
        sys.exit(0)
    
    cookies = args.cookies_string
    dir_path = Path(args.directory).resolve()
    ign_file_path = Path(args.ignore_file).resolve() if args.ignore_file else None
    ign_patterns = args.ignore
    media_format = args.format
    
    if not dir_path.is_dir():
        raise ValueError(f'Directory does not exist: {dir_path}')
    
    if args.ignore:
        log.warning(f'BandcampSync is bypassing: {ign_patterns}')
    
    if args.temp_dir:
        temp_dir = Path(args.temp_dir).resolve()
        if not temp_dir.is_dir():
            raise ValueError(f'Temporary directory does not exist: {temp_dir}')
    else:
        temp_dir = None
    
    if args.notify_url:
        notify_url = args.notify_url
        log.info(f'BandcampSync will notify: {notify_url}')
    else:
        notify_url = None
    
    log.info(f'BandcampSync v{version} starting (container mode)')
    log.info(f'Cookies loaded from command line argument')
    
    do_sync(cookies, dir_path, media_format, temp_dir, ign_file_path, ign_patterns, notify_url)
    log.info('Done')


if __name__ == '__main__':
    main()
