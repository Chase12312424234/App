export type Drop = { time: number; score: number; confidence: number };

export type Entry = {
  start: number;
  end: number;
  title: string | null;
  artist: string | null;
  isrc: string | null;
  hits: number;
  uncertain: boolean;
  links: Record<string, string>;
  drop: Drop | null;
  extra: { cover?: string; shazam_url?: string };
};

export type Result = {
  info: { video_id: string; title: string; uploader: string | null; webpage_url: string };
  duration: number;
  entries: Entry[];
  usage: { requests: number; samples: number; matched: number; cached: number };
};

export type Job = {
  id: string;
  video_id: string;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  message: string;
  samples_done: number;
  samples_total: number;
  tracks_found: number;
  error: string | null;
  queue_position: number;
  cached?: boolean;
  result?: Result;
};

export type Recent = { video_id: string; title: string; track_count: number };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = `Request failed (${r.status})`;
    try {
      const body = await r.json();
      if (typeof body.detail === "string") msg = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return r.json();
}

export const api = {
  createJob: (url: string, force = false) =>
    req<Job>("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, force }),
    }),
  getJob: (id: string) => req<Job>(`/api/jobs/${id}`),
  recent: () => req<Recent[]>("/api/recent"),
  exportUrl: (videoId: string, drops: boolean) =>
    `/api/sets/${videoId}.txt${drops ? "?drops=1" : ""}`,
};

/** Follow a job until it finishes: SSE first, polling as a fallback. */
export function watchJob(id: string, onUpdate: (j: Job) => void): () => void {
  let closed = false;
  let timer: number | undefined;
  let es: EventSource | null = null;

  const finish = async () => {
    const full = await api.getJob(id);
    if (!closed) onUpdate(full);
  };

  const poll = async () => {
    if (closed) return;
    try {
      const j = await api.getJob(id);
      onUpdate(j);
      if (j.status === "done" || j.status === "error") return;
    } catch {
      /* transient; try again */
    }
    timer = window.setTimeout(poll, 2000);
  };

  if ("EventSource" in window) {
    es = new EventSource(`/api/jobs/${id}/events`);
    es.onmessage = (ev) => {
      const j: Job = JSON.parse(ev.data);
      if (j.status === "done") {
        es?.close();
        finish();
      } else {
        onUpdate(j);
        if (j.status === "error") es?.close();
      }
    };
    es.onerror = () => {
      es?.close();
      if (!closed) poll();
    };
  } else {
    poll();
  }

  return () => {
    closed = true;
    es?.close();
    if (timer) clearTimeout(timer);
  };
}

export function fmtTime(sec: number, forceHours = false): string {
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h || forceHours ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${String(m).padStart(2, "0")}:${ss}`;
}

export function videoIdFrom(url: string): string | null {
  const t = url.trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(t)) return t;
  const m = t.match(/(?:v=|youtu\.be\/|\/shorts\/|\/live\/|\/embed\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : null;
}
