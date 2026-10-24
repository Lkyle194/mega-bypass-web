"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Link, type Mega, type State } from "@/lib/api";

const POLL_MS = 5000;

export default function Home() {
  const [state, setState] = useState<State | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api.state();
      setState(s);
      setOnline(true);
      setErr(null);
    } catch (e: any) {
      setOnline(false);
      setErr(e.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, POLL_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  const addLinks = async () => {
    const urls = input
      .split(/[\n,]+/)
      .map((u) => u.trim())
      .filter(Boolean);
    if (!urls.length) return;
    setBusy(true);
    try {
      await api.addLinks(urls);
      setInput("");
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const delLink = async (id: number) => {
    try {
      await api.deleteLink(id);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const retryLink = async (id: number) => {
    try {
      await api.retryLink(id);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const delMega = async (id: number) => {
    try {
      await api.deleteMega(id);
      await refresh();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const copyText = async (text: string, key: number) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(key);
    setTimeout(() => setCopied(null), 1200);
  };

  const links = state?.links ?? [];
  const mega = state?.mega ?? [];

  return (
    <main>
      <h1>Mega Bypass</h1>
      <p className="sub">
        Coller vos liens bypass → le Mac passe la chaîne (bypass.vip → … → MEGA).
      </p>

      <div className="statusbar">
        <span className={`dot ${online ? "on" : online === false ? "err" : ""}`} />
        {online === null
          ? "Connexion au Mac…"
          : online
          ? "Worker Mac en ligne"
          : `Mac injoignable (${err})`}
        {state?.worker?.running && state?.worker?.current_url && (
          <span>· traite {state.worker.current_url}</span>
        )}
      </div>

      <div className="panel">
        <h2>Ajouter des liens</h2>
        <textarea
          placeholder="Collez ici un lien par ligne (linkvertise, mega, …)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <div className="row" style={{ marginTop: 10 }}>
          <button onClick={addLinks} disabled={busy || !input.trim()}>
            {busy ? "Ajout…" : "Ajouter à la file"}
          </button>
          {err && <span className="hint" style={{ color: "var(--err)" }}>{err}</span>}
        </div>
      </div>

      <div className="panel">
        <h2>
          File d'attente <span className="count">({links.length})</span>
        </h2>
        {links.length === 0 ? (
          <div className="empty">Aucun lien en file.</div>
        ) : (
          <ul className="items">
            {links.map((l: Link) => (
              <li key={l.id} className="item">
                <span
                  className={`badge ${
                    l.status === "dead"
                      ? "dead"
                      : l.status === "failed"
                      ? "dead"
                      : l.status === "processing"
                      ? "processing"
                      : "pending"
                  }`}
                >
                  {l.status}
                  {l.attempts > 0 ? ` ${l.attempts}/${l.max_attempts}` : ""}
                </span>
                <span className="url" title={l.url}>
                  {l.last_host ? `${l.last_host} · ` : ""}
                  {l.url}
                  {l.last_error ? ` — ${l.last_error}` : ""}
                </span>
                <button
                  className="ghost sm"
                  onClick={() => copyText(l.url, l.id)}
                  title="Copier"
                >
                  {copied === l.id ? "✓" : "Copier"}
                </button>
                <button
                  className="ghost sm"
                  onClick={() => retryLink(l.id)}
                  title="Relancer"
                >
                  Relancer
                </button>
                <button
                  className="danger sm"
                  onClick={() => delLink(l.id)}
                  title="Supprimer"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="panel">
        <h2>
          Liens MEGA récupérés <span className="count">({mega.length})</span>
        </h2>
        {mega.length === 0 ? (
          <div className="empty">Aucun lien MEGA pour l'instant.</div>
        ) : (
          <>
            <div className="row" style={{ marginBottom: 8 }}>
              <button
                className="mega-btn sm"
                onClick={() =>
                  copyText(
                    mega.map((m: Mega) => m.url).join("\n"),
                    -1
                  )
                }
                disabled={mega.length === 0}
              >
                {copied === -1 ? "✓ Copié" : "Tout copier"}
              </button>
            </div>
            <ul className="items">
              {mega.map((m: Mega) => (
                <li key={m.id} className="item">
                  <span className="badge ok">MEGA</span>
                  <span className="url" title={m.url}>
                    {m.url}
                    {m.hops ? ` (${m.hops} hops)` : ""}
                    {m.source_url ? ` ← ${m.source_url}` : ""}
                  </span>
                  <button
                    className="ghost sm"
                    onClick={() => copyText(m.url, m.id)}
                  >
                    {copied === m.id ? "✓" : "Copier"}
                  </button>
                  <button
                    className="danger sm"
                    onClick={() => delMega(m.id)}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </main>
  );
}
