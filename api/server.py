#!/usr/bin/env python3
"""
BurnerNet Post Board API
Listens on port 3000; lighttpd proxies /api/* to here.
Persists to /var/lib/burnernet/posts.json with atomic writes + a process lock
so simultaneous posters don't clobber each other.
"""
import json
import os
import re
import subprocess
import threading
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DATA_DIR = os.environ.get('BURNERNET_DATA_DIR', '/var/lib/burnernet')
DATA_FILE = os.path.join(DATA_DIR, 'posts.json')
LED_PORTAL_FILE = os.path.join(DATA_DIR, 'led-portal.json')
LED_PORTAL_TTL = 8.0
LED_PORTAL_GUEST_TTL = 30.0
LED_PORTAL_MAX_GUESTS = 50
PORT = int(os.environ.get('BURNERNET_PORT', '3000'))
# Stamped onto every new post. Historical posts keep whatever burn they were saved with.
CURRENT_BURN = os.environ.get('BURNERNET_CURRENT_BURN', 'Microburn 2026')
SET_TIME_BIN = os.environ.get('BURNERNET_SET_TIME', '/usr/local/bin/burnernet-set-time')
_TIME_STAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}$')

_lock = threading.Lock()
_led_lock = threading.Lock()


def _ensure_dir():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass


def _load():
    _ensure_dir()
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(posts):
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(prefix='posts-', suffix='.json', dir=DATA_DIR)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(posts, f, ensure_ascii=False)
        os.replace(tmp, DATA_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _clean_str(s, limit=4000):
    if not isinstance(s, str):
        return ''
    return s.strip()[:limit]


def _new_id():
    return f"{int(time.time() * 1000)}-{os.urandom(3).hex()}"


def _time_status():
    ntp = None
    ntp_synced = None
    timezone = time.strftime('%Z')
    try:
        out = subprocess.check_output(
            ['timedatectl', 'show', '-p', 'Timezone', '-p', 'NTP', '-p', 'NTPSynchronized'],
            text=True,
            timeout=3,
        )
        for line in out.splitlines():
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            if k == 'Timezone':
                timezone = v.strip()
            elif k == 'NTP':
                ntp = v.strip().lower() == 'yes'
            elif k == 'NTPSynchronized':
                ntp_synced = v.strip().lower() == 'yes'
    except Exception:
        pass
    return {
        'unix_ms': int(time.time() * 1000),
        'local': time.strftime('%Y-%m-%d %H:%M:%S'),
        'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'timezone': timezone,
        'tz_offset': time.strftime('%z'),
        'ntp': ntp,
        'ntp_synced': ntp_synced,
    }


def _stamp_from_body(body):
    """Wall-clock in the Pi's timezone: YYYY-MM-DDTHH:MM:SS, or unix_ms from the phone."""
    stamp = _clean_str(body.get('local') or body.get('iso') or '', limit=32)
    if stamp:
        if len(stamp) == 16 and stamp[10] == 'T':
            stamp = stamp + ':00'
        stamp = stamp.replace(' ', 'T', 1)
        if _TIME_STAMP_RE.match(stamp):
            return stamp
        return None
    raw = body.get('unix_ms')
    try:
        unix_ms = int(raw)
    except (TypeError, ValueError):
        return None
    # Reject nonsense / y2k38-adjacent junk from a broken client
    if unix_ms < 1_000_000_000_000 or unix_ms > 4_000_000_000_000:
        return None
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(unix_ms / 1000.0))


def _client_unix_ms(body, fallback_ms: int) -> int:
    """Prefer the poster's phone clock; fall back to the Pi if the value is junk."""
    raw = body.get('timestamp', body.get('unix_ms'))
    try:
        unix_ms = int(raw)
    except (TypeError, ValueError):
        return fallback_ms
    # ~2020-05 through ~2036 — wide enough for a wrong Pi, tight enough to drop garbage.
    if unix_ms < 1_600_000_000_000 or unix_ms > 2_100_000_000_000:
        return fallback_ms
    return unix_ms


def _set_time(stamp: str):
    try:
        r = subprocess.run(
            ['sudo', '-n', SET_TIME_BIN, stamp],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return False, 'set-time helper is not installed'
    except Exception as e:
        return False, str(e)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or 'set-time failed').strip()
        return False, err
    return True, (r.stdout or '').strip()


def _read_led_portal():
    try:
        with open(LED_PORTAL_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {'phase': 'idle', 'ts': 0, 'guests': {}}


def _led_portal_aggregate(data: dict):
    now = time.time()
    guests = data.get('guests') if isinstance(data.get('guests'), dict) else {}
    kept = {}
    for cid, entry in guests.items():
        if not isinstance(entry, dict):
            continue
        try:
            ts = float(entry.get('ts', 0))
        except (TypeError, ValueError):
            continue
        if now - ts > LED_PORTAL_GUEST_TTL:
            continue
        kept[str(cid)[:64]] = {
            'phase': 'connecting' if entry.get('phase') == 'connecting' else 'idle',
            'ts': ts,
        }
    connecting = any(
        g.get('phase') == 'connecting' and (now - float(g.get('ts', 0))) <= LED_PORTAL_TTL
        for g in kept.values()
    )
    # Legacy single-phase file (no guests)
    if not kept and data.get('phase') == 'connecting':
        try:
            ts = float(data.get('ts', 0))
        except (TypeError, ValueError):
            ts = 0
        connecting = (now - ts) <= LED_PORTAL_TTL
    return {
        'phase': 'connecting' if connecting else 'idle',
        'ts': now,
        'guests': kept,
    }


def _write_led_portal(phase: str, client_id: str):
    _ensure_dir()
    data = _read_led_portal()
    guests = data.get('guests') if isinstance(data.get('guests'), dict) else {}
    cid = client_id or 'anon'
    guests[cid] = {'phase': phase, 'ts': time.time()}
    if len(guests) > LED_PORTAL_MAX_GUESTS:
        # Drop oldest
        ordered = sorted(guests.items(), key=lambda kv: float((kv[1] or {}).get('ts', 0) or 0))
        guests = dict(ordered[-LED_PORTAL_MAX_GUESTS:])
    payload = _led_portal_aggregate({'guests': guests})
    fd, tmp = tempfile.mkstemp(prefix='led-portal-', suffix='.json', dir=DATA_DIR)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
        os.replace(tmp, LED_PORTAL_FILE)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = 'BurnerNetAPI/1.0'

    def _json(self, code, body):
        payload = json.dumps(body).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length <= 0 or length > 100_000:
            return None
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode('utf-8'))
        except Exception:
            return None

    def log_message(self, fmt, *args):
        # Quiet by default; systemd captures stdout if needed
        pass

    # GET /api/posts
    # GET /api/led-portal
    # GET /api/time
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/posts':
            with _lock:
                posts = _load()
            return self._json(200, posts)
        if path == '/api/led-portal':
            with _led_lock:
                return self._json(200, _led_portal_aggregate(_read_led_portal()))
        if path == '/api/time':
            return self._json(200, _time_status())
        return self._json(404, {'error': 'not found'})

    # POST /api/posts
    # POST /api/posts/<id>/replies
    # POST /api/posts/<id>/archive
    # POST /api/led-portal  {"phase": "connecting"|"idle", "client": "..."}
    # POST /api/time  {"unix_ms": 1778...} or {"local": "2026-09-05T15:52:00"}
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json() or {}

        if path == '/api/time':
            stamp = _stamp_from_body(body)
            if not stamp:
                return self._json(400, {'error': 'send unix_ms or local YYYY-MM-DDTHH:MM:SS'})
            ok, detail = _set_time(stamp)
            status = _time_status()
            if not ok:
                status['error'] = detail
                return self._json(500, status)
            status['set_to'] = stamp
            return self._json(200, status)

        if path == '/api/led-portal':
            phase = _clean_str(body.get('phase', ''), limit=32).lower()
            if phase not in ('connecting', 'idle'):
                return self._json(400, {'error': 'phase must be connecting or idle'})
            client = _clean_str(body.get('client', ''), limit=64) or 'anon'
            with _led_lock:
                return self._json(200, _write_led_portal(phase, client))

        if path == '/api/posts':
            author = _clean_str(body.get('author', '')) or 'Anonymous'
            content = _clean_str(body.get('content', ''))
            if not content:
                return self._json(400, {'error': 'content required'})
            post = {
                'id': _new_id(),
                'author': author,
                'content': content,
                'timestamp': _client_unix_ms(body, int(time.time() * 1000)),
                'burn': CURRENT_BURN,
                'archived': False,
            }
            with _lock:
                posts = _load()
                posts.append(post)
                _save(posts)
            return self._json(200, post)

        m = re.match(r'^/api/posts/([^/]+)/archive$', path)
        if m:
            pid = m.group(1)
            archived = bool(body.get('archived', True))
            with _lock:
                posts = _load()
                for p in posts:
                    if p.get('id') == pid:
                        p['archived'] = archived
                        _save(posts)
                        return self._json(200, p)
            return self._json(404, {'error': 'post not found'})

        return self._json(404, {'error': 'not found'})


def main():
    _ensure_dir()
    httpd = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f"BurnerNet API listening on 127.0.0.1:{PORT}, data {DATA_FILE}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == '__main__':
    main()
