#!/usr/bin/env python
"""
Container-friendly bandcampsync runner.

This script:
1. Takes cookies as a direct string argument (no temp files needed)
2. Monkey patches requests to use curl_cffi for better TLS fingerprinting
"""

import sys
import argparse
from pathlib import Path

# Monkey patch requests with curl_cffi BEFORE importing bandcampsync
def patch_requests():
    """Replace requests with curl_cffi.requests for better TLS fingerprinting"""
    try:
        from curl_cffi import requests as curl_requests
        import requests
        
        # Wrap curl_cffi Response to support context manager protocol
        class ContextManagerResponse:
            """Wrapper to add context manager support to curl_cffi Response"""
            def __init__(self, response):
                self._response = response
            
            def __enter__(self):
                return self._response
            
            def __exit__(self, *args):
                self._response.close()
            
            def __getattr__(self, name):
                return getattr(self._response, name)
        
        # Patch the session class
        class PatchedSession(curl_requests.Session):
            """Wrapper to make curl_cffi.Session compatible with requests.Session API"""
            def __init__(self, *args, **kwargs):
                # curl_cffi uses impersonate parameter for browser TLS fingerprint
                super().__init__(impersonate="chrome", *args, **kwargs)
            
            def request(self, method, url, **kwargs):
                response = super().request(method, url, **kwargs)
                return ContextManagerResponse(response)
            
            def get(self, url, **kwargs):
                response = super().get(url, **kwargs)
                return ContextManagerResponse(response)
            
            def post(self, url, **kwargs):
                response = super().post(url, **kwargs)
                return ContextManagerResponse(response)
        
        requests.Session = PatchedSession
        
        # Patch module-level functions
        _curl_session = PatchedSession()
        
        def _wrap_get(url, **kwargs):
            return _curl_session.get(url, **kwargs)
        
        def _wrap_post(url, **kwargs):
            return _curl_session.post(url, **kwargs)
        
        requests.get = _wrap_get
        requests.post = _wrap_post
        requests.put = _curl_session.put
        requests.delete = _curl_session.delete
        requests.head = _curl_session.head
        requests.options = _curl_session.options
        requests.patch = _curl_session.patch
        
        print("Successfully patched requests with curl_cffi", file=sys.stderr)
        return True
    except ImportError as e:
        print(f"Warning: curl_cffi not available, using standard requests: {e}", file=sys.stderr)
        return False


# Apply the patch before any bandcampsync imports
patch_requests()

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
    
    # Pass None for cookies_path since we don't have a file
    do_sync(None, cookies, dir_path, media_format, temp_dir, ign_file_path, ign_patterns, notify_url)
    log.info('Done')


if __name__ == '__main__':
    main()
