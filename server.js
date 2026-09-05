// Local dev server. On the Pi, lighttpd serves files and proxies /api/* to api/server.py.
// This Node server mimics both so we can preview the intranet locally.
const http = require('http');
const fs = require('fs');
const path = require('path');
const port = process.env.PORT || 3456;

const mime = {
  '.html': 'text/html', '.js': 'application/javascript',
  '.json': 'application/json', '.css': 'text/css',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'
};

// In-memory + on-disk store for local /api/posts
const CURRENT_BURN = process.env.BURNERNET_CURRENT_BURN || 'Microburn 2026';
const DATA_FILE = path.join(__dirname, '.api-posts.json');
let posts = [];
try { posts = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8')); } catch {}
function save() { try { fs.writeFileSync(DATA_FILE, JSON.stringify(posts)); } catch {} }
function newId() { return Date.now() + '-' + Math.random().toString(36).slice(2, 8); }

function readBody(req) {
  return new Promise((resolve) => {
    let raw = '';
    req.on('data', c => raw += c);
    req.on('end', () => { try { resolve(JSON.parse(raw || '{}')); } catch { resolve({}); } });
  });
}

function jsonRes(res, code, body) {
  const payload = JSON.stringify(body);
  res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(payload);
}

async function handleApi(req, res, urlPath) {
  if (urlPath === '/api/time') {
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    const local = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate())
      + ' ' + pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
    if (req.method === 'GET') {
      return jsonRes(res, 200, {
        unix_ms: now.getTime(),
        local,
        iso: local.replace(' ', 'T'),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        tz_offset: now.toTimeString().slice(9, 15),
        ntp: null,
        ntp_synced: null,
      });
    }
    if (req.method === 'POST') {
      return jsonRes(res, 501, { error: 'setting the clock only works on the Pi' });
    }
  }
  if (req.method === 'GET' && urlPath === '/api/posts') {
    return jsonRes(res, 200, posts);
  }
  if (req.method === 'POST' && urlPath === '/api/posts') {
    const body = await readBody(req);
    const content = (body.content || '').toString().trim().slice(0, 4000);
    if (!content) return jsonRes(res, 400, { error: 'content required' });
    const post = {
      id: newId(),
      author: (body.author || 'Anonymous').toString().trim().slice(0, 200),
      content,
      timestamp: (function () {
        const n = parseInt(body.timestamp || body.unix_ms, 10);
        if (n >= 1600000000000 && n <= 2100000000000) return n;
        return Date.now();
      })(),
      burn: CURRENT_BURN,
      archived: false
    };
    posts.push(post);
    save();
    return jsonRes(res, 200, post);
  }
  const m = urlPath.match(/^\/api\/posts\/([^/]+)\/archive$/);
  if (m && req.method === 'POST') {
    const body = await readBody(req);
    const post = posts.find(p => p.id === m[1]);
    if (!post) return jsonRes(res, 404, { error: 'post not found' });
    post.archived = body.archived !== false;
    save();
    return jsonRes(res, 200, post);
  }
  return jsonRes(res, 404, { error: 'not found' });
}

http.createServer((req, res) => {
  const urlPath = decodeURIComponent(req.url.split('?')[0]);
  if (urlPath.startsWith('/api/')) return handleApi(req, res, urlPath);
  const filePath = path.join(__dirname, urlPath);
  const ext = path.extname(filePath).toLowerCase();
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Not found'); return; }
    res.writeHead(200, { 'Content-Type': mime[ext] || 'application/octet-stream' });
    res.end(data);
  });
}).listen(port, () => console.log(`Server running on port ${port}`));
