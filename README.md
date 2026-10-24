# Mega Bypass — webapp

UI statique (Next.js, export `out/`) qui pilote la chaîne de bypass vers MEGA.

- **Vercel** : cette UI (add / delete / copy, status, poll 5 s).
- **Mac** : le worker réel (`queue/queue_server.py` + `queue/worker.py` sur le port **8085**) qui lance `chain2.py` (cloakbrowser + bionic/oMLX).

## Brancher sur le Mac

L'UI appelle `QUEUE_BASE` (`src/lib/api.ts`).
- En local : `http://127.0.0.1:8085` (défaut).
- En production (Vercel) : mettre l'URL **Tailscale Funnel** du Mac, ex. :
  ```
  const QUEUE_BASE = "https://mac-mini-de-laurent.tail4ff741.ts.net:8085";
  ```
  (ou via `window.__MBCONFIG__.queueBase` injecté à l'import de `api.ts`).

## Déployer

```bash
git push  # → CI Vercel
# ou manuel :
vercel --prod --yes --token "$VERCEL_TOKEN"
```

## Worker sur le Mac

```bash
# file (port 8085)
python3 queue/queue_server.py
# worker (traite la file)
QUEUE_URL=http://127.0.0.1:8085 ~/Projects/mega-bypass/venv/bin/python queue/worker.py
```

## Structure

- `src/app/page.tsx` — UI (file + MEGA)
- `src/lib/api.ts` — client API du Mac
- `queue/queue_server.py` — API file (SQLite)
- `queue/worker.py` — boucle worker (launch chain2.py)
