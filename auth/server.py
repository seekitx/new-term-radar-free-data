"""Single-user gateway for the new-term-radar site. Secrets live outside the repo."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import secrets
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

CONFIG = json.loads(Path('/app/credentials.json').read_text(encoding='utf-8'))
ORIGIN = 'https://terms.aifluxor.com'
COOKIE = '__Host-terms_session'
SESSION_SECONDS = 12 * 60 * 60
MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
sessions = {}
failures = []
guard = threading.Lock()

LOGIN_HTML = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>登录 · 新词雷达</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:#f5f6ef;color:#1c382d;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}.shell{min-height:100vh;display:grid;grid-template-columns:minmax(300px,1fr) minmax(420px,1fr)}.intro{background:#163e32;color:#eff9ed;padding:48px 8vw;display:flex;flex-direction:column;position:relative;overflow:hidden}.brand{display:flex;align-items:center;gap:12px;font-weight:650;font-size:16px}.mark{display:grid;place-items:center;width:42px;height:42px;border:1px solid #83aa8b;border-radius:50%;color:#d6ebba;font-size:22px}.brand small{display:block;font-weight:400;font-size:10px;letter-spacing:.14em;color:#a7c5b1;margin-top:4px}.hero{margin:auto 0;max-width:470px;position:relative}.kicker{font-size:11px;letter-spacing:.17em;color:#b2d596;font-weight:700}.hero h1{font-size:clamp(34px,4vw,52px);line-height:1.22;letter-spacing:-.04em;margin:20px 0}.hero p{font-size:15px;line-height:1.9;color:#bdd3c4}.orbit{position:absolute;width:390px;height:390px;border:1px solid rgba(194,229,174,.14);border-radius:50%;right:-145px;top:-165px}.orbit:before,.orbit:after{content:"";position:absolute;border:1px solid rgba(194,229,174,.12);border-radius:50%}.orbit:before{inset:40px}.orbit:after{inset:90px}.aside-foot{font-size:11px;letter-spacing:.08em;color:#9ebaaa}.entry{display:grid;place-items:center;padding:45px 28px}.card{width:min(410px,100%)}.card-label{color:#71917a;letter-spacing:.13em;font-size:11px;font-weight:700}.card h2{font-size:30px;letter-spacing:-.04em;margin:12px 0 8px}.desc{color:#788d80;font-size:13px;line-height:1.7;margin:0 0 30px}.field{display:block;margin:19px 0 8px;font-size:12px;font-weight:650;color:#3f5a49}input{width:100%;height:48px;border:1px solid #d6e2d5;border-radius:8px;background:#fff;padding:0 14px;font:inherit;color:#244133;outline:none}input:focus{border-color:#5a9871;box-shadow:0 0 0 3px #dceee0}.submit{width:100%;height:49px;background:#246749;color:white;border:0;border-radius:8px;font-size:14px;font-weight:650;margin-top:26px;cursor:pointer}.submit:hover{background:#19573d}.message{background:#fff2eb;color:#a54f3a;border:1px solid #f1d8cf;padding:11px 13px;border-radius:8px;font-size:12px;line-height:1.6;margin:18px 0}.hint{color:#90a194;font-size:11px;line-height:1.7;margin-top:23px}@media(max-width:760px){.shell{display:block}.intro{min-height:220px;padding:30px 26px}.hero{margin:38px 0 8px}.hero h1{font-size:30px;margin:13px 0}.hero p{font-size:13px}.aside-foot,.orbit{display:none}.entry{padding:38px 25px 60px}.card h2{font-size:27px}}
</style></head><body><main class="shell"><section class="intro"><div class="brand"><span class="mark">✳</span><div>新词雷达<small>NEW TERM RADAR</small></div></div><div class="hero"><div class="kicker">EARLY SIGNALS, CLEARER DECISIONS</div><h1>更早发现，<br>值得研究的线索。</h1><p>从公开来源追踪新出现的项目、需求与网站变化。登录后继续查看你的雷达。</p><div class="orbit" aria-hidden="true"></div></div><div class="aside-foot">NEW TERM RADAR / 每日公开来源观察</div></section><section class="entry"><div class="card"><div class="card-label">WELCOME BACK</div><h2>登录新词雷达</h2><p class="desc">输入你的账号和密码，继续访问工作台。</p>{message}<form method="post" action="/login" autocomplete="on"><label class="field" for="username">账号</label><input id="username" name="username" type="text" autocomplete="username" required autofocus maxlength="100"><label class="field" for="password">密码</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="200"><button class="submit" type="submit">登 录　 →</button></form><p class="hint">你的登录状态会保留一段时间。退出后可重新登录。</p></div></section></main></body></html>'''


def valid_session(header: str) -> bool:
    jar = cookies.SimpleCookie()
    try:
        jar.load(header)
        value = jar[COOKIE].value if COOKIE in jar else ''
    except cookies.CookieError:
        return False
    now = time.time()
    with guard:
        expiry = sessions.get(value, 0)
        if expiry <= now:
            sessions.pop(value, None)
            return False
        return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never write credentials, cookies or request bodies to the logs.

    def respond(self, status, payload=b'', headers=()):
        self.send_response(status)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Length', str(len(payload)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    def redirect(self, location, cookie=None):
        headers = [('Location', location)]
        if cookie:
            headers.append(('Set-Cookie', cookie))
        self.respond(303, headers=headers)

    def show_login(self, message='', status=200):
        error = '<div class="message" role="alert">' + html.escape(message) + '</div>' if message else ''
        body = LOGIN_HTML.replace('{message}', error).encode('utf-8')
        self.respond(status, body, [('Content-Type', 'text/html; charset=utf-8'), ('X-Frame-Options', 'DENY')])

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/check':
            self.respond(204 if valid_session(self.headers.get('Cookie', '')) else 401)
        elif path == '/login':
            if valid_session(self.headers.get('Cookie', '')):
                self.redirect('/')
            else:
                self.show_login()
        else:
            self.respond(404)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        origin = self.headers.get('Origin', '')
        if origin and origin != ORIGIN:
            self.respond(403)
            return
        if path == '/logout':
            jar = cookies.SimpleCookie()
            try:
                jar.load(self.headers.get('Cookie', ''))
                token = jar[COOKIE].value if COOKIE in jar else ''
            except cookies.CookieError:
                token = ''
            with guard:
                sessions.pop(token, None)
            self.redirect('/login', f'{COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict')
            return
        if path != '/login':
            self.respond(404)
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2048 or not self.headers.get('Content-Type', '').startswith('application/x-www-form-urlencoded'):
                self.respond(400)
                return
            form = parse_qs(self.rfile.read(size).decode('utf-8'), max_num_fields=4)
            username = form.get('username', [''])[0][:100]
            password = form.get('password', [''])[0][:200]
        except (ValueError, UnicodeDecodeError):
            self.respond(400)
            return
        now = time.time()
        with guard:
            failures[:] = [t for t in failures if t > now - LOCK_SECONDS]
            if len(failures) >= MAX_FAILURES:
                locked = True
                good = False
            else:
                locked = False
                derived = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(CONFIG['salt']), CONFIG['iterations'])
                good = hmac.compare_digest(username, CONFIG['username']) and hmac.compare_digest(derived, bytes.fromhex(CONFIG['password_hash']))
                if not good:
                    failures.append(now)
                else:
                    failures.clear()
                    for token in [key for key, expiry in sessions.items() if expiry <= now]:
                        sessions.pop(token, None)
                    token = secrets.token_urlsafe(32)
                    sessions[token] = now + SESSION_SECONDS
        if locked:
            self.show_login('尝试次数过多，请 15 分钟后再试。', 429)
        elif not good:
            self.show_login('账号或密码不正确，请重试。', 401)
        else:
            self.redirect('/', f'{COOKIE}={token}; Path=/; Max-Age={SESSION_SECONDS}; Secure; HttpOnly; SameSite=Strict')


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
