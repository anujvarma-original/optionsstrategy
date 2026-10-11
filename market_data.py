"""Isolated Yahoo requests with hard timeouts; no provider imports at app startup."""
import json
import subprocess
import sys
from pathlib import Path

FETCH_TIMEOUT = 12


def fetch_snapshot(symbol, days, tolerance, today_iso):
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), '--worker', symbol,
             str(days), str(tolerance), today_iso],
            capture_output=True, text=True, timeout=FETCH_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # subprocess.run kills and reaps the child; no abandoned Yahoo request.
        raise TimeoutError(f'{symbol}: market data exceeded {FETCH_TIMEOUT}s; try again later.') from exc
    if completed.returncode != 0:
        raise RuntimeError(f'{symbol}: market-data worker failed (exit {completed.returncode}).')
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'{symbol}: invalid provider response.') from exc
    if 'error' in payload:
        raise RuntimeError(payload['error'])
    return payload['snapshot']


def worker():
    import contextlib
    from datetime import date
    from types import SimpleNamespace
    from options_scanner import fetch
    _, _, symbol, days, tolerance, today_iso = sys.argv
    args = SimpleNamespace(days=int(days), expiry_tolerance=int(tolerance))
    try:
        with contextlib.redirect_stdout(sys.stderr):
            snapshot = fetch(symbol, args, date.fromisoformat(today_iso))
        payload = {'snapshot': snapshot}
    except Exception as exc:
        payload = {'error': f'{type(exc).__name__}: {exc}'}
    print(json.dumps(payload, default=str))


if __name__ == '__main__':
    worker()
