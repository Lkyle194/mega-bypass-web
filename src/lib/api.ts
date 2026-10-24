// Client API vers le worker Mac (queue_server.py).
// En local : 127.0.0.1:8085. En production (Vercel) : Tailscale Funnel du Mac
// (port 443 par défaut — le port 8085 externe n'est pas servi).
const FUNNEL = "https://mac-mini-de-laurent.tail4ff741.ts.net";
export const QUEUE_BASE =
  (typeof window !== "undefined" &&
    (window as any).__MBCONFIG__?.queueBase) ||
  (process.env.NEXT_PUBLIC_QUEUE_BASE ||
    (typeof window !== "undefined" &&
      window.location.hostname.endsWith(".vercel.app")
      ? FUNNEL
      : "http://127.0.0.1:8085"));

export type Link = {
  id: number;
  url: string;
  status: "pending" | "processing" | "failed" | "done" | "dead";
  attempts: number;
  max_attempts: number;
  created_at: string;
  last_run_at?: string;
  last_host?: string | null;
  hop_count?: number;
  last_error?: string | null;
};

export type Mega = {
  id: number;
  url: string;
  source_url?: string;
  source_link_id?: number | null;
  hops?: number;
  recovered_at: string;
};

export type Worker = {
  running: string | boolean;
  current_url?: string | null;
  current_link_id?: number | null;
};

export type State = {
  ok: boolean;
  links: Link[];
  mega: Mega[];
  worker: Worker;
  max_attempts: number;
};

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(`${QUEUE_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      if (j.error) msg = j.error;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  state: () => req<State>("/api/state"),
  addLinks: (urls: string[]) =>
    req<{ added: string[]; skipped: string[] }>("/api/links", {
      method: "POST",
      body: JSON.stringify({ urls }),
    }),
  deleteLink: (id: number) =>
    req<{ ok: boolean }>(`/api/links/${id}`, { method: "DELETE" }),
  retryLink: (id: number) =>
    req<{ ok: boolean }>(`/api/links/${id}/retry`, { method: "POST" }),
  deleteMega: (id: number) =>
    req<{ ok: boolean }>(`/api/mega/${id}`, { method: "DELETE" }),
};
