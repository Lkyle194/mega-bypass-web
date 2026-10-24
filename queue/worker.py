#!/usr/bin/env python3
"""mega-bypass-web — worker local (cote Mac).

Boucle : prend 1 lien de la file (GET /api/pick), lance chain2.py dessus dans un
process isolee (sorties dans /tmp/queue-<id>/), lit le resultat, et :
  - lien MEGA recupere  -> le lien de base est retire de la file, le mega est ajoute
  - echec / boucle      -> re-queue (pending) tant que attempts < max, sinon failed

Le worker DOIT tourner sur le Mac avec le venv cloakbrowser + acces aux LLMs locaux
(bionic:1234 et oMLX:8000). C'est le seul proces qui les utilise.

Env :
  QUEUE_URL   base du serveur file (defaut http://127.0.0.1:8085)
  QUEUE_PORT  (defaut 8085)
  CHAIN2_PY   chemin de chain2.py (defaut ~/Projects/mega-bypass/chain2.py)
  CHAIN2_PYTHON  interprete a utiliser (defaut: le venv courant si cloakbrowser dispo)
  WORKER_SLEEP  secondes d'attente si file vide (defaut 20)
"""
import json, os, re, sys, time, urllib.request, urllib.error, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
HOMEP = os.path.expanduser("~")

QUEUE_URL = os.environ.get("QUEUE_URL", "http://127.0.0.1:8085").rstrip("/")
CHAIN2_PY = os.environ.get("CHAIN2_PY", os.path.join(HOMEP, "Projects/mega-bypass/chain2.py"))
WORKER_SLEEP = int(os.environ.get("WORKER_SLEEP", "20"))
CHAIN_TIMEOUT = int(os.environ.get("CHAIN_TIMEOUT", "2000"))  # s


def qpy():
    """Interprete avec cloakbrowser."""
    v = os.environ.get("CHAIN2_PYTHON")
    if v:
        return v
    cand = os.path.join(HOMEP, "Projects/mega-bypass/venv/bin/python")
    if os.path.exists(cand):
        return cand
    # fallback: le python courant (le worker est lui-meme lance avec le bon venv)
    return sys.executable


def http(method, path, body=None, timeout=15):
    url = QUEUE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return f.status, json.loads(f.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"_err": str(e)}


def set_worker(**kv):
    http("POST", "/api/worker", kv)


def finish(link_id, ok, mega_url=None, host=None, hops=None, error=None):
    http("POST", f"/api/links/{link_id}/finish",
         {"ok": ok, "mega_url": mega_url, "host": host, "hops": hops, "error": error})


MEGA_RE = re.compile(r"https?://(?:mega\.(?:nz|co\.nz|io|us|de|org)|1f\.app)/[A-Za-z0-9?=&_%/.-]+")


def extract_mega(chain):
    """Cherche un lien mega dans la chaine (mega ou les hops), garde le fragment #."""
    cand = [chain.get("mega")] + chain.get("hops", [])
    for c in cand:
        if not c:
            continue
        m = MEGA_RE.search(c)
        if m:
            return m.group(0)
    # fallback : le champ mega direct
    return chain.get("mega") if chain.get("mega") else None


def run_chain(link, lid):
    """Lance chain2.py sur un lien. Retourne (mega_url|None, status, host, hops, error)."""
    workdir = f"/tmp/queue-{lid}-{int(time.time())}"
    os.makedirs(workdir, exist_ok=True)
    env = dict(os.environ)
    env["CHAIN2_META"] = f"{workdir}/meta.json"
    env["CHAIN2_LOG"] = f"{workdir}/chain2.log"
    env["CHAIN2_CAP"] = f"{workdir}/caps"
    os.makedirs(env["CHAIN2_CAP"], exist_ok=True)

    py = qpy()
    print(f"[worker] {link}  ->  {py} {CHAIN2_PY}  (workdir {workdir})", flush=True)
    t0 = time.time()
    try:
        proc = subprocess.run(
            [py, CHAIN2_PY, link],
            cwd=os.path.dirname(CHAIN2_PY),
            env=env,
            stdout=open(f"{workdir}/stdout.log", "w"),
            stderr=subprocess.STDOUT,
            timeout=CHAIN_TIMEOUT)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = 124
        print(f"[worker] TIMEOUT {link} after {time.time()-t0:.0f}s", flush=True)
    print(f"[worker] done rc={rc} in {time.time()-t0:.0f}s", flush=True)

    # lit le resultat
    meta = env["CHAIN2_META"]
    chain = None
    if os.path.exists(meta):
        try:
            out = json.load(open(meta))
            chains = out.get("chains", [])
            chain = chains[0] if chains else None
        except Exception as e:
            print(f"[worker] meta parse err: {e}", flush=True)

    mega = extract_mega(chain) if chain else None
    hops = len(chain.get("hops", [])) if chain else 0
    status = chain.get("status") if chain else None
    host = None
    if chain and chain.get("hops"):
        hh = chain["hops"][-1]
        hm = re.match(r"https?://([^/]+)", hh)
        host = hm.group(1) if hm else None

    ok = bool(mega)
    error = None if ok else (status or f"rc={rc}")
    return mega, status, host, hops, error, ok


def worker_healthy():
    st, _ = http("GET", "/api/state")
    return st == 200


def main():
    print(f"[worker] start  queue={QUEUE_URL}  chain2={CHAIN2_PY}  py={qpy()}", flush=True)
    time.sleep(2)
    while True:
        if not worker_healthy():
            print("[worker] queue server injoignable, retry en 15s", flush=True)
            set_worker(running=False)
            time.sleep(15)
            continue
        st, row = http("GET", "/api/pick", timeout=10)
        if st != 200 or not row.get("id"):
            set_worker(running=False, current_url=None, current_link_id=None)
            time.sleep(WORKER_SLEEP)
            continue
        lid = row["id"]; link = row["url"]
        print(f"[worker] pris lien #{lid} {link}", flush=True)
        set_worker(running=True, current_url=link, current_link_id=lid)
        try:
            mega, status, host, hops, error, ok = run_chain(link, lid)
        except Exception as e:
            mega, status, host, hops, error, ok = None, None, None, 0, f"exc:{str(e)[:200]}", False
        finish(lid, ok, mega_url=mega, host=host, hops=hops,
               error=(None if ok else (error or status)))
        set_worker(running=False, current_url=None, current_link_id=None)
        if ok:
            print(f"[worker] #{lid} MEGA OK -> {mega}", flush=True)
        else:
            print(f"[worker] #{lid} pas de mega ({status}/{error}), re-queue", flush=True)
        time.sleep(8)


if __name__ == "__main__":
    main()
