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
import threading
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DATA_DIR = os.environ.get('BURNERNET_DATA_DIR', '/var/lib/burnernet')
DATA_FILE = os.path.join(DATA_DIR, 'posts.json')
LED_PORTAL_FILE = os.path.join(DATA_DIR, 'led-portal.json')
PORT = int(os.environ.get('BURNERNET_PORT', '3000'))

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


def _read_led_portal():
    try:
        with open(LED_PORTAL_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {'phase': 'idle', 'ts': 0}


def _write_led_portal(phase: str):
    _ensure_dir()
    payload = {'phase': phase, 'ts': time.time()}
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
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/posts':
            with _lock:
                posts = _load()
            return self._json(200, posts)
        if path == '/api/led-portal':
            with _led_lock:
                return self._json(200, _read_led_portal())
        return self._json(404, {'error': 'not found'})

    # POST /api/posts
    # POST /api/posts/<id>/replies
    # POST /api/posts/<id>/archive
    # POST /api/led-portal  {"phase": "connecting"|"idle"}
    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json() or {}

        if path == '/api/led-portal':
            phase = _clean_str(body.get('phase', ''), limit=32).lower()
            if phase not in ('connecting', 'idle'):
                return self._json(400, {'error': 'phase must be connecting or idle'})
            with _led_lock:
                return self._json(200, _write_led_portal(phase))

        if path == '/api/posts':
            author = _clean_str(body.get('author', '')) or 'Anonymous'
            content = _clean_str(body.get('content', ''))
            if not content:
                return self._json(400, {'error': 'content required'})
            post = {
                'id': _new_id(),
                'author': author,
                'content': content,
                'timestamp': int(time.time() * 1000),
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
