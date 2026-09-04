# -*- coding: utf-8 -*-
"""
그냥전당포.com 서버 (WSGI)
- Python 표준 라이브러리만 사용 (외부 패키지 불필요)
- 로컬 실행: python server.py  (기본 포트 8080, 변경: python server.py 8123)
- 호스팅 배포: WSGI 앱 `server:application` (예: gunicorn server:application)
- 데이터: data/pawnshop.db (자동 생성)
- 관리자: 첫 실행 후 /admin 접속 → 초기 비밀번호 설정
"""
import base64
import sqlite3
import json
import hashlib
import hmac
import os
import re
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "pawnshop.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

MAX_BODY = 16 * 1024               # 요청 본문 최대 16KB
MAX_IMAGE_BODY = 6 * 1024 * 1024   # 이미지 포함 요청(구매신청) 최대 6MB
RETENTION_DAYS = 7                 # 신청 기록 보관 기간 (지나면 자동 삭제)
SESSION_HOURS = 24 * 7             # 관리자 로그인 유지 기간

VALID_STATUS = ("대기", "승인", "거절", "완료")

# ---------------------------------------------------------------- DB

db_lock = threading.Lock()
_conn = None


def db():
    global _conn
    if _conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def init_db():
    c = db()
    with db_lock:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sell_requests (   -- 감정신청 (유저가 파는 것)
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            item TEXT NOT NULL,
            qty TEXT NOT NULL,
            price TEXT NOT NULL,          -- 감정가 (사장님이 감정 후 입력)
            delivery TEXT NOT NULL,       -- '우편' = 우편으로 보내둠 / '직접' = 직접 전달 예정
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '대기',
            admin_note TEXT NOT NULL DEFAULT '',
            received INTEGER NOT NULL DEFAULT 0,  -- 관리자가 우편 물품 수령 확인
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS buy_requests (    -- 구매신청 (유저가 사는 것)
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname TEXT NOT NULL,
            item TEXT NOT NULL,
            qty TEXT NOT NULL,
            price TEXT NOT NULL,          -- 정가 (재고 주문 시 자동 기록)
            note TEXT NOT NULL DEFAULT '',
            stock_id INTEGER,             -- 판매 재고에서 주문한 경우
            status TEXT NOT NULL DEFAULT '대기',
            admin_note TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stock (           -- 판매 중인 물품
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            price TEXT NOT NULL,
            qty INTEGER NOT NULL DEFAULT 1,
            note TEXT NOT NULL DEFAULT '',
            visible INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );
        """)
        c.commit()
        try:
            c.execute("ALTER TABLE buy_requests ADD COLUMN image TEXT NOT NULL DEFAULT ''")
            c.commit()
        except sqlite3.OperationalError:
            pass  # 이미 컬럼 있음
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        if get_setting("secret") is None:
            set_setting("secret", secrets.token_hex(32))
        if get_setting("notice") is None:
            set_setting("notice", "어서오세요! 그냥전당포입니다.")
        if get_setting("shop_open") is None:
            set_setting("shop_open", "1")


def get_setting(key):
    row = db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key, value):
    db().execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    db().commit()

# ---------------------------------------------------------------- 자동 삭제

_last_purge = 0.0


def remove_upload(fname):
    if fname and re.match(r"^buy_\d+\.(jpg|png|webp)$", fname):
        try:
            os.remove(os.path.join(UPLOAD_DIR, fname))
        except OSError:
            pass


def purge_old():
    """RETENTION_DAYS 지난 신청 기록(+캡쳐 이미지) 삭제. 1시간에 한 번만 실제 수행."""
    global _last_purge
    if time.time() - _last_purge < 3600:
        return
    _last_purge = time.time()
    cutoff = now() - RETENTION_DAYS * 86400
    with db_lock:
        rows = db().execute(
            "SELECT image FROM buy_requests WHERE created_at<? AND image!=''", (cutoff,)).fetchall()
        for r in rows:
            remove_upload(r["image"])
        db().execute("DELETE FROM sell_requests WHERE created_at<?", (cutoff,))
        db().execute("DELETE FROM buy_requests WHERE created_at<?", (cutoff,))
        db().commit()

# ---------------------------------------------------------------- 인증

def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 120000).hex()


def set_admin_password(password):
    salt = secrets.token_hex(16)
    set_setting("admin_salt", salt)
    set_setting("admin_pw", hash_pw(password, salt))


def check_admin_password(password):
    salt = get_setting("admin_salt")
    stored = get_setting("admin_pw")
    if not salt or not stored:
        return False
    return hmac.compare_digest(stored, hash_pw(password, salt))


def make_session_token():
    exp = str(int(time.time()) + SESSION_HOURS * 3600)
    sig = hmac.new(get_setting("secret").encode(), exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_session_token(token):
    try:
        exp, sig = token.split(".", 1)
        if int(exp) < time.time():
            return False
        expect = hmac.new(get_setting("secret").encode(), exp.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expect, sig)
    except Exception:
        return False


def session_cookie(token):
    return f"session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={SESSION_HOURS*3600}"

# ---------------------------------------------------------------- 유틸

def now():
    return int(time.time())


def clean(text, maxlen):
    """문자열 필드 정리: 공백 정리 + 길이 제한"""
    if not isinstance(text, str):
        return ""
    return re.sub(r"\s+", " ", text).strip()[:maxlen]


def row_dicts(rows):
    return [dict(r) for r in rows]

# ---------------------------------------------------------------- WSGI 기반

STATUS_TEXT = {
    200: "200 OK", 400: "400 Bad Request", 401: "401 Unauthorized",
    404: "404 Not Found", 500: "500 Internal Server Error",
}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


class Request:
    """WSGI environ을 감싼 요청 객체."""

    def __init__(self, environ):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET")
        self.path = environ.get("PATH_INFO", "/")

    def query(self):
        return urllib.parse.parse_qs(self.environ.get("QUERY_STRING", ""))

    def read_json(self, limit=MAX_BODY):
        try:
            length = int(self.environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return None
        if length <= 0 or length > limit:
            return None
        try:
            return json.loads(self.environ["wsgi.input"].read(length).decode())
        except Exception:
            return None

    def is_admin(self):
        cookie = self.environ.get("HTTP_COOKIE") or ""
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "session" and verify_session_token(v):
                return True
        return False


class Response:
    """핸들러가 반환하는 응답 객체."""

    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or []


def json_resp(obj, status=200, set_cookie=None):
    body = json.dumps(obj, ensure_ascii=False).encode()
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Cache-Control", "no-store"),
    ]
    if set_cookie:
        headers.append(("Set-Cookie", set_cookie))
    return Response(body, status, headers)


def serve_static(path):
    if path == "/":
        path = "/index.html"
    elif path == "/admin":
        path = "/admin.html"
    fname = os.path.normpath(path.lstrip("/"))
    if fname.startswith("..") or os.path.isabs(fname) or ":" in fname:
        return Response("Not Found".encode(), 404, [("Content-Type", "text/plain")])
    fpath = os.path.join(PUBLIC_DIR, fname)
    if not os.path.isfile(fpath):
        return Response("Not Found".encode(), 404, [("Content-Type", "text/plain")])
    with open(fpath, "rb") as f:
        data = f.read()
    ext = os.path.splitext(fpath)[1].lower()
    ctype = MIME.get(ext, "application/octet-stream")
    cache = "no-cache" if ext in (".html", ".css", ".js") else "public, max-age=86400"
    return Response(data, 200, [("Content-Type", ctype), ("Cache-Control", cache)])

# ---------------------------------------------------------------- 유저 API

def api_shop(req):
    with db_lock:
        stock = db().execute(
            "SELECT id,item,price,qty,note FROM stock WHERE visible=1 AND qty>0 ORDER BY id DESC"
        ).fetchall()
    return json_resp({
        "notice": get_setting("notice"),
        "open": get_setting("shop_open") == "1",
        "stock": row_dicts(stock),
    })


def api_my(req):
    nickname = clean((req.query().get("nickname") or [""])[0], 30)
    if not nickname:
        return json_resp({"error": "닉네임을 입력하세요."}, 400)
    with db_lock:
        sell = db().execute(
            "SELECT id,item,qty,price,delivery,status,admin_note,created_at "
            "FROM sell_requests WHERE nickname=? COLLATE NOCASE ORDER BY id DESC LIMIT 50",
            (nickname,)).fetchall()
        buy = db().execute(
            "SELECT id,item,qty,price,status,admin_note,created_at "
            "FROM buy_requests WHERE nickname=? COLLATE NOCASE ORDER BY id DESC LIMIT 50",
            (nickname,)).fetchall()
    return json_resp({"sell": row_dicts(sell), "buy": row_dicts(buy)})


def api_sell(req):
    d = req.read_json()
    if d is None:
        return json_resp({"error": "잘못된 요청"}, 400)
    nickname = clean(d.get("nickname"), 30)
    item = clean(d.get("item"), 60)
    qty = clean(str(d.get("qty", "")), 30)
    delivery = d.get("delivery")
    note = clean(d.get("note"), 200)
    if not nickname or not item or not qty:
        return json_resp({"error": "닉네임/물품/수량은 필수입니다."}, 400)
    if delivery not in ("우편", "직접"):
        return json_resp({"error": "전달 방법을 선택하세요."}, 400)
    with db_lock:
        # 가격(감정가)은 사장님이 감정 후 입력
        db().execute(
            "INSERT INTO sell_requests(nickname,item,qty,price,delivery,note,created_at,updated_at) "
            "VALUES(?,?,?,'',?,?,?,?)",
            (nickname, item, qty, delivery, note, now(), now()))
        db().commit()
    return json_resp({"ok": True})


def api_buy(req):
    d = req.read_json(limit=MAX_IMAGE_BODY)
    if d is None:
        return json_resp({"error": "잘못된 요청 (이미지가 너무 크면 다시 시도해주세요)"}, 400)
    nickname = clean(d.get("nickname"), 30)
    item = clean(d.get("item"), 60)
    qty = clean(str(d.get("qty", "")), 30)
    note = clean(d.get("note"), 200)
    stock_id = d.get("stock_id")
    if stock_id is not None and not isinstance(stock_id, int):
        stock_id = None
    if not nickname or not item or not qty:
        return json_resp({"error": "닉네임/물품/수량은 필수입니다."}, 400)
    # 입금내역 캡쳐 (dataURL) 디코딩
    img_bytes, img_ext = None, None
    image_data = d.get("image") or ""
    if image_data:
        m = re.match(r"^data:image/(png|jpeg|jpg|webp);base64,", image_data)
        if not m:
            return json_resp({"error": "이미지 형식이 올바르지 않습니다."}, 400)
        try:
            img_bytes = base64.b64decode(image_data[m.end():])
        except Exception:
            return json_resp({"error": "이미지 형식이 올바르지 않습니다."}, 400)
        if len(img_bytes) > 4 * 1024 * 1024:
            return json_resp({"error": "이미지가 너무 큽니다 (4MB 이하)."}, 400)
        img_ext = "jpg" if m.group(1) in ("jpeg", "jpg") else m.group(1)
    if stock_id and not img_bytes:
        return json_resp({"error": "정가 물품 주문은 먼저 입금하고 입금내역 캡쳐를 첨부해야 합니다."}, 400)
    with db_lock:
        # 가격은 고정: 재고 주문이면 판매가를 그대로 기록
        price = ""
        if stock_id:
            srow = db().execute("SELECT price FROM stock WHERE id=?", (stock_id,)).fetchone()
            if srow:
                price = srow["price"]
        cur = db().execute(
            "INSERT INTO buy_requests(nickname,item,qty,price,note,stock_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (nickname, item, qty, price, note, stock_id, now(), now()))
        rid = cur.lastrowid
        if img_bytes:
            fname = f"buy_{rid}.{img_ext}"
            with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
                f.write(img_bytes)
            db().execute("UPDATE buy_requests SET image=? WHERE id=?", (fname, rid))
        db().commit()
    return json_resp({"ok": True})

# ---------------------------------------------------------------- 관리자 API

def api_admin_state(req):
    return json_resp({
        "needs_setup": get_setting("admin_pw") is None,
        "logged_in": req.is_admin(),
    })


def api_admin_setup(req):
    if get_setting("admin_pw") is not None:
        return json_resp({"error": "이미 비밀번호가 설정되어 있습니다."}, 400)
    d = req.read_json() or {}
    pw = d.get("password") or ""
    if len(pw) < 4:
        return json_resp({"error": "비밀번호는 4자 이상으로 하세요."}, 400)
    set_admin_password(pw)
    return json_resp({"ok": True}, set_cookie=session_cookie(make_session_token()))


def api_admin_login(req):
    d = req.read_json() or {}
    time.sleep(0.3)  # 무차별 대입 완화
    if not check_admin_password(d.get("password") or ""):
        return json_resp({"error": "비밀번호가 틀렸습니다."}, 401)
    return json_resp({"ok": True}, set_cookie=session_cookie(make_session_token()))


def api_admin_logout(req):
    return json_resp({"ok": True},
                     set_cookie="session=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict")


def api_admin_data(req):
    with db_lock:
        sell = db().execute("SELECT * FROM sell_requests ORDER BY id DESC LIMIT 300").fetchall()
        buy = db().execute("SELECT * FROM buy_requests ORDER BY id DESC LIMIT 300").fetchall()
        stock = db().execute("SELECT * FROM stock ORDER BY id DESC LIMIT 300").fetchall()
    return json_resp({
        "sell": row_dicts(sell),
        "buy": row_dicts(buy),
        "stock": row_dicts(stock),
        "notice": get_setting("notice"),
        "open": get_setting("shop_open") == "1",
    })


def api_admin_image(req):
    """구매신청 입금내역 캡쳐 이미지 (관리자 전용)"""
    try:
        rid = int((req.query().get("id") or ["0"])[0])
    except ValueError:
        rid = 0
    with db_lock:
        row = db().execute("SELECT image FROM buy_requests WHERE id=?", (rid,)).fetchone()
    fname = row["image"] if row else ""
    if not fname or not re.match(r"^buy_\d+\.(jpg|png|webp)$", fname):
        return json_resp({"error": "이미지가 없습니다."}, 404)
    fpath = os.path.join(UPLOAD_DIR, fname)
    if not os.path.isfile(fpath):
        return json_resp({"error": "이미지가 없습니다."}, 404)
    with open(fpath, "rb") as f:
        data = f.read()
    ctype = "image/jpeg" if fname.endswith(".jpg") else ("image/png" if fname.endswith(".png") else "image/webp")
    return Response(data, 200, [("Content-Type", ctype), ("Cache-Control", "private, max-age=3600")])


def api_admin_request(req):
    """감정/구매 신청 상태 변경·삭제.
    {kind:'sell'|'buy', id, status?, admin_note?, price?, received?, delete?}"""
    d = req.read_json() or {}
    kind = d.get("kind")
    rid = d.get("id")
    if kind not in ("sell", "buy") or not isinstance(rid, int):
        return json_resp({"error": "잘못된 요청"}, 400)
    table = "sell_requests" if kind == "sell" else "buy_requests"
    with db_lock:
        row = db().execute(f"SELECT * FROM {table} WHERE id=?", (rid,)).fetchone()
        if not row:
            return json_resp({"error": "없는 신청입니다."}, 404)
        if d.get("delete"):
            if kind == "buy" and row["image"]:
                remove_upload(row["image"])
            db().execute(f"DELETE FROM {table} WHERE id=?", (rid,))
            db().commit()
            return json_resp({"ok": True})
        fields, values = [], []
        if "price" in d:  # 감정가 (사장님이 입력)
            fields.append("price=?")
            values.append(clean(str(d["price"]), 60))
        if "status" in d:
            if d["status"] not in VALID_STATUS:
                return json_resp({"error": "잘못된 상태"}, 400)
            fields.append("status=?")
            values.append(d["status"])
            # 재고 연동 구매신청을 완료 처리하면 재고 수량 차감
            if kind == "buy" and d["status"] == "완료" and row["status"] != "완료" and row["stock_id"]:
                db().execute("UPDATE stock SET qty=MAX(0, qty-1) WHERE id=?", (row["stock_id"],))
        if "admin_note" in d:
            fields.append("admin_note=?")
            values.append(clean(d["admin_note"], 200))
        if kind == "sell" and "received" in d:
            fields.append("received=?")
            values.append(1 if d["received"] else 0)
        if not fields:
            return json_resp({"error": "변경할 내용이 없습니다."}, 400)
        fields.append("updated_at=?")
        values.append(now())
        values.append(rid)
        db().execute(f"UPDATE {table} SET {','.join(fields)} WHERE id=?", values)
        db().commit()
    return json_resp({"ok": True})


def api_admin_stock(req):
    """재고 관리. {action:'add'|'update'|'delete', ...}"""
    d = req.read_json() or {}
    action = d.get("action")
    with db_lock:
        if action == "add":
            item = clean(d.get("item"), 60)
            price = clean(str(d.get("price", "")), 60)
            qty = d.get("qty")
            note = clean(d.get("note"), 200)
            if not item or not price or not isinstance(qty, int) or qty < 0:
                return json_resp({"error": "물품/가격/수량을 확인하세요."}, 400)
            db().execute(
                "INSERT INTO stock(item,price,qty,note,created_at) VALUES(?,?,?,?,?)",
                (item, price, qty, note, now()))
        elif action == "update":
            sid = d.get("id")
            if not isinstance(sid, int):
                return json_resp({"error": "잘못된 요청"}, 400)
            fields, values = [], []
            if "item" in d:
                fields.append("item=?"); values.append(clean(d["item"], 60))
            if "price" in d:
                fields.append("price=?"); values.append(clean(str(d["price"]), 60))
            if "qty" in d and isinstance(d["qty"], int) and d["qty"] >= 0:
                fields.append("qty=?"); values.append(d["qty"])
            if "note" in d:
                fields.append("note=?"); values.append(clean(d["note"], 200))
            if "visible" in d:
                fields.append("visible=?"); values.append(1 if d["visible"] else 0)
            if not fields:
                return json_resp({"error": "변경할 내용이 없습니다."}, 400)
            values.append(sid)
            db().execute(f"UPDATE stock SET {','.join(fields)} WHERE id=?", values)
        elif action == "delete":
            sid = d.get("id")
            if not isinstance(sid, int):
                return json_resp({"error": "잘못된 요청"}, 400)
            db().execute("DELETE FROM stock WHERE id=?", (sid,))
        else:
            return json_resp({"error": "잘못된 요청"}, 400)
        db().commit()
    return json_resp({"ok": True})


def api_admin_settings(req):
    d = req.read_json() or {}
    if "notice" in d:
        set_setting("notice", clean(d["notice"], 500))
    if "open" in d:
        set_setting("shop_open", "1" if d["open"] else "0")
    return json_resp({"ok": True})


def api_admin_password(req):
    d = req.read_json() or {}
    if not check_admin_password(d.get("old") or ""):
        return json_resp({"error": "현재 비밀번호가 틀렸습니다."}, 400)
    pw = d.get("new") or ""
    if len(pw) < 4:
        return json_resp({"error": "새 비밀번호는 4자 이상으로 하세요."}, 400)
    set_admin_password(pw)
    return json_resp({"ok": True})

# ---------------------------------------------------------------- 라우팅

GET_ROUTES = {
    "/api/shop": api_shop,
    "/api/my": api_my,
    "/api/admin/state": api_admin_state,
}
GET_ADMIN_ROUTES = {
    "/api/admin/data": api_admin_data,
    "/api/admin/image": api_admin_image,
}
POST_ROUTES = {
    "/api/sell": api_sell,
    "/api/buy": api_buy,
    "/api/admin/setup": api_admin_setup,
    "/api/admin/login": api_admin_login,
    "/api/admin/logout": api_admin_logout,
}
POST_ADMIN_ROUTES = {
    "/api/admin/request": api_admin_request,
    "/api/admin/stock": api_admin_stock,
    "/api/admin/settings": api_admin_settings,
    "/api/admin/password": api_admin_password,
}

_init_done = False
_init_lock = threading.Lock()


def handle(req):
    global _init_done
    if not _init_done:
        with _init_lock:
            if not _init_done:
                init_db()
                _init_done = True
    if req.path.startswith("/api/"):
        purge_old()
    if req.method == "GET" or req.method == "HEAD":
        if req.path in GET_ROUTES:
            return GET_ROUTES[req.path](req)
        if req.path in GET_ADMIN_ROUTES:
            if not req.is_admin():
                return json_resp({"error": "로그인이 필요합니다."}, 401)
            return GET_ADMIN_ROUTES[req.path](req)
        if req.path.startswith("/api/"):
            return json_resp({"error": "없는 API"}, 404)
        return serve_static(req.path)
    if req.method == "POST":
        if req.path in POST_ROUTES:
            return POST_ROUTES[req.path](req)
        if req.path in POST_ADMIN_ROUTES:
            if not req.is_admin():
                return json_resp({"error": "로그인이 필요합니다."}, 401)
            return POST_ADMIN_ROUTES[req.path](req)
        return json_resp({"error": "없는 API"}, 404)
    return json_resp({"error": "지원하지 않는 메서드"}, 404)


def application(environ, start_response):
    """WSGI 진입점. 호스팅에서는 `server:application` 으로 지정."""
    req = Request(environ)
    try:
        res = handle(req)
    except Exception as e:
        res = json_resp({"error": "서버 오류: " + str(e)}, 500)
    headers = list(res.headers)
    headers.append(("Content-Length", str(len(res.body))))
    start_response(STATUS_TEXT.get(res.status, f"{res.status} Error"), headers)
    if req.method == "HEAD":
        return [b""]
    return [res.body]

# ---------------------------------------------------------------- 로컬 실행

def main():
    from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler

    class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
        daemon_threads = True
        allow_reuse_address = True

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, fmt, *args):
            pass

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    init_db()
    with make_server("0.0.0.0", port, application,
                     server_class=ThreadingWSGIServer, handler_class=QuietHandler) as httpd:
        print(f"[그냥전당포] 서버 시작: http://localhost:{port}")
        print(f"[그냥전당포] 관리자 페이지: http://localhost:{port}/admin")
        print("[그냥전당포] 종료: Ctrl+C")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
