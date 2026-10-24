#!/usr/bin/env python3
"""mega-bypass-web — serveur de file d'attente (cote Mac).

Petit serveur HTTP local (port 8085) qui expose la file de liens a bypass et les
liens MEGA recuperes. Il est le seul source de verite : la webapp (Vercel) l'appelle
via le tunnel, et le worker local le consulte pour prendre des liens.

Stockage : SQLite (queue/queue.db) — pas de dep, gratuit, local, persistant.

Endpoints :
  GET    /api/state                 -> tout l'etat (links + mega + worker)
  POST   /api/links                 {url} ou {urls:[...]}  -> ajoute (dedupe par url)
  DELETE /api/links/<id>            -> retire un lien de base
  POST   /api/links/<id>/retry      -> re-queue (reset attempts, status pending)
  DELETE /api/mega/<id>             -> retire un lien mega
  GET    /api/pick                  -> worker : 1 lien pending (ou 404)
  POST   /api/worker                {running, current_url, current_link_id} -> etat worker
CORS ouvert (la webapp est sur un autre domaine / tunnel).
"""
import json, os, sqlite3, threading, time, re, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("QUEUE_DB", os.path.join(HERE, "queue.db"))
PORT = int(os.environ.get("QUEUE_PORT", "8085"))
MAX_ATTEMPTS = int(os.environ.get("QUEUE_MAX_ATTEMPTS", "3"))

MEGA_RE = re.compile(r"mega\.(?:nz|co\.nz|io|us|de|org)|1f\.app", re.I)
LOCK = threading.Lock()


def _conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with LOCK:
        c = _conn()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS links (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              url TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL DEFAULT 'pending',
              attempts INTEGER NOT NULL DEFAULT 0,
              max_attempts INTEGER NOT NULL DEFAULT 3,
              created_at TEXT NOT NULL,
              last_run_at TEXT,
              last_host TEXT,
              hop_count INTEGER,
              last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS mega (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              url TEXT NOT NULL,
              source_url TEXT,
              source_link_id INTEGER,
              recovered_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS worker (
              key TEXT PRIMARY KEY,
              value TEXT
            );
            """
        )
        c.commit()
        c.close()


def norm(url):
    url = (url or "").strip().strip("\"'").strip()
    if url and not url.startswith("http"):
        url = "https://" + url
    return url or None


def host_of(url):
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else None


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---------- data ----------
def state():
    with LOCK:
        c = _conn()
        links = [dict(r) for r in c.execute(
            "SELECT * FROM links ORDER BY status != 'done', created_at")]
        mega = [dict(r) for r in c.execute(
            "SELECT * FROM mega ORDER BY recovered_at DESC")]
        wrow = [dict(r) for r in c.execute("SELECT * FROM worker")]
        c.close()
    worker = {r["key"]: r["value"] for r in wrow}
    return {"links": links, "mega": mega, "worker": worker,
            "ts": now(), "port": PORT}


def add_links(urls):
    added, skipped = [], []
    for u in urls:
        u = norm(u)
        if not u:
            continue
        with LOCK:
            c = _conn()
            try:
                ex = c.execute("SELECT id,status FROM links WHERE url=?", (u,)).fetchone()
                if ex:
                    skipped.append(u)
                else:
                    c.execute(
                        "INSERT INTO links(url,status,attempts,max_attempts,created_at) VALUES(?,?,?,?,?)",
                        (u, "pending", 0, MAX_ATTEMPTS, now()))
                    c.commit()
                    added.append(u)
            finally:
                c.close()
    return added, skipped


def delete_link(link_id):
    with LOCK:
        c = _conn()
        c.execute("DELETE FROM links WHERE id=?", (link_id,))
        c.commit(); n = c.total_changes; c.close()
    return n


def retry_link(link_id):
    with LOCK:
        c = _conn()
        c.execute("UPDATE links SET status='pending', attempts=0, last_error=NULL WHERE id=?", (link_id,))
        c.commit(); n = c.total_changes; c.close()
    return n


def delete_mega(mega_id):
    with LOCK:
        c = _conn()
        c.execute("DELETE FROM mega WHERE id=?", (mega_id,))
        c.commit(); n = c.total_changes; c.close()
    return n


def pick():
    """Worker : prend 1 lien pending (le plus ancien) et le passe en processing."""
    with LOCK:
        c = _conn()
        row = c.execute(
            "SELECT * FROM links WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            c.close(); return None
        c.execute("UPDATE links SET status='processing', last_run_at=? WHERE id=?",
                  (now(), row["id"]))
        c.commit()
        out = dict(row); out["status"] = "processing"
        c.close()
    return out


def set_worker(**kv):
    with LOCK:
        c = _conn()
        for k, v in kv.items():
            c.execute(
                "INSERT INTO worker(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, json.dumps(v) if not isinstance(v, (str, type(None))) else v))
        c.commit(); c.close()


def finish_link(link_id, ok, mega_url=None, host=None, hops=None, error=None):
    """Worker : declenche le resultat. ok=True -> lien retire (mega recupere).
    ok=False -> re-queue (pending) si attempts<max, sinon failed."""
    with LOCK:
        c = _conn()
        row = c.execute("SELECT * FROM links WHERE id=?", (link_id,)).fetchone()
        if row:
            att = row["attempts"] + 1
            if ok:
                # lien de base retire de la file
                c.execute("DELETE FROM links WHERE id=?", (link_id,))
                if mega_url:
                    c.execute(
                        "INSERT INTO mega(url,source_url,source_link_id,recovered_at) VALUES(?,?,?,?)",
                        (mega_url, row["url"], link_id, now()))
            else:
                newst = "failed" if att >= row["max_attempts"] else "pending"
                c.execute(
                    "UPDATE links SET attempts=?, status=?, last_error=?, last_host=?, hop_count=? WHERE id=?",
                    (att, newst, error, host, hops, link_id))
        c.commit(); c.close()


# ---------- http ----------
class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/api/state":
            self._json(200, state())
        elif p == "/api/pick":
            row = pick()
            if row:
                self._json(200, row)
            else:
                self._json(404, {"error": "empty"})
        elif p == "/":
            self._json(200, {"ok": True, "msg": "mega-bypass queue", "links": len(state()["links"])})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        b = self._body()
        if p == "/api/links":
            urls = b.get("urls") or ([b["url"]] if b.get("url") else [])
            # on accepte aussi un texte multi-lignes
            if not urls and b.get("text"):
                urls = [l for l in b["text"].splitlines() if l.strip()]
            added, skipped = add_links(urls)
            self._json(200, {"added": added, "skipped": skipped})
        elif p == "/api/worker":
            set_worker(**b)
            self._json(200, {"ok": True})
        elif re.match(r"^/api/links/\d+/retry$", p):
            lid = int(re.search(r"\d+", p).group())
            self._json(200, {"ok": retry_link(lid) > 0})
        elif re.match(r"^/api/links/\d+/finish$", p):
            lid = int(re.search(r"\d+", p).group())
            finish_link(lid, b.get("ok", False), b.get("mega_url"),
                        b.get("host"), b.get("hops"), b.get("error"))
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})

    def do_DELETE(self):
        p = urllib.parse.urlparse(self.path).path
        if re.match(r"^/api/links/\d+$", p):
            lid = int(re.search(r"\d+", p).group())
            self._json(200, {"ok": delete_link(lid) > 0})
        elif re.match(r"^/api/mega/\d+$", p):
            mid = int(re.search(r"\d+", p).group())
            self._json(200, {"ok": delete_mega(mid) > 0})
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, *a):
        pass


def main():
    init_db()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print(f"[queue] server on 0.0.0.0:{PORT}  db={DB}  max_attempts={MAX_ATTEMPTS}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
