import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fmtTime, videoIdFrom, watchJob, type Entry, type Job, type Recent, type Result } from "./api";
import { loadYouTubeApi, type YTPlayer } from "./youtube";

const PREVIEW_SECONDS = 15;
const LEAD_IN = 3; // start this many seconds before the drop

export default function App() {
  const [url, setUrl] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [recent, setRecent] = useState<Recent[]>([]);
  const stopWatching = useRef<(() => void) | null>(null);

  const refreshRecent = useCallback(() => {
    api.recent().then(setRecent).catch(() => {});
  }, []);

  const start = useCallback(
    async (input: string, force = false) => {
      setFormError(null);
      const vid = videoIdFrom(input);
      if (!vid) {
        setFormError("Paste a YouTube video link, like https://www.youtube.com/watch?v=…");
        return;
      }
      stopWatching.current?.();
      setResult(null);
      setJob(null);
      const params = new URLSearchParams(window.location.search);
      if (params.get("v") !== vid) {
        params.set("v", vid);
        window.history.pushState(null, "", `?${params}`);
      }
      try {
        const j = await api.createJob(input, force);
        setJob(j);
        if (j.status === "done" && j.result) {
          setResult(j.result);
          return;
        }
        stopWatching.current = watchJob(j.id, (u) => {
          setJob(u);
          if (u.status === "done" && u.result) {
            setResult(u.result);
            refreshRecent();
          }
        });
      } catch (e) {
        setFormError((e as Error).message);
      }
    },
    [refreshRecent],
  );

  // deep links: /?v=VIDEO_ID
  useEffect(() => {
    refreshRecent();
    const fromUrl = () => {
      const v = new URLSearchParams(window.location.search).get("v");
      if (v) {
        const link = `https://www.youtube.com/watch?v=${v}`;
        setUrl(link);
        start(link);
      } else {
        stopWatching.current?.();
        setJob(null);
        setResult(null);
      }
    };
    fromUrl();
    window.addEventListener("popstate", fromUrl);
    return () => window.removeEventListener("popstate", fromUrl);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const goHome = () => {
    stopWatching.current?.();
    setJob(null);
    setResult(null);
    setUrl("");
    window.history.pushState(null, "", window.location.pathname);
    refreshRecent();
  };

  return (
    <div className="app">
      <header className="top">
        <button className="logo" onClick={goHome} aria-label="DropFinder home">
          <Wave /> <span>DROP</span>
          <span className="accent">FINDER</span>
        </button>
      </header>

      <main>
        <section className={`hero ${job || result ? "compact" : ""}`}>
          {!job && !result && (
            <>
              <h1>
                Every track. <span className="accent">Every drop.</span>
              </h1>
              <p className="sub">Paste a YouTube DJ set. Get the tracklist with timestamps, links, and a button that jumps straight to each drop.</p>
            </>
          )}
          <form
            className="search"
            onSubmit={(e) => {
              e.preventDefault();
              start(url);
            }}
          >
            <input
              type="url"
              inputMode="url"
              placeholder="https://www.youtube.com/watch?v=…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              aria-label="YouTube link"
              required
            />
            <button type="submit" disabled={job?.status === "running" || job?.status === "queued"}>
              Find tracks
            </button>
          </form>
          {formError && <p className="form-error">{formError}</p>}
        </section>

        {job && !result && job.status !== "error" && <ProgressCard job={job} />}
        {job?.status === "error" && (
          <div className="card error-card" role="alert">
            <h2>Couldn't process this set</h2>
            <p>{job.error}</p>
            <button className="ghost" onClick={() => start(url || `https://youtu.be/${job.video_id}`)}>
              Try again
            </button>
          </div>
        )}
        {result && <ResultView key={result.info.video_id} result={result} cached={!!job?.cached} onRedo={() => start(url, true)} />}

        {!job && !result && recent.length > 0 && (
          <section className="recent">
            <h2>Recently found</h2>
            <ul>
              {recent.map((r) => (
                <li key={r.video_id}>
                  <button
                    onClick={() => {
                      const link = `https://www.youtube.com/watch?v=${r.video_id}`;
                      setUrl(link);
                      start(link);
                    }}
                  >
                    <img src={`https://i.ytimg.com/vi/${r.video_id}/mqdefault.jpg`} alt="" loading="lazy" />
                    <span className="r-title">{r.title}</span>
                    <span className="r-count">{plural(r.track_count, "track")}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>
      <footer>Tracks identified by audio fingerprinting · audio plays from YouTube</footer>
    </div>
  );
}

function ProgressCard({ job }: { job: Job }) {
  const steps = [
    { id: "downloading", label: "Download" },
    { id: "identifying", label: "Identify" },
    { id: "analyzing", label: "Find drops" },
  ];
  const stageIdx = job.status === "queued" ? -1 : steps.findIndex((s) => s.id === job.stage);
  const pct = job.samples_total ? Math.round((job.samples_done / job.samples_total) * 100) : 0;
  const headline =
    job.status === "queued"
      ? job.queue_position > 0
        ? `In the queue: ${job.queue_position} set${job.queue_position > 1 ? "s" : ""} ahead of yours`
        : "Starting…"
      : job.stage === "identifying"
        ? `Identified ${job.tracks_found} track${job.tracks_found === 1 ? "" : "s"} so far…`
        : job.message;

  return (
    <div className="card progress" aria-live="polite">
      <div className="eq" aria-hidden>
        {Array.from({ length: 5 }).map((_, i) => (
          <i key={i} style={{ animationDelay: `${i * 0.12}s` }} />
        ))}
      </div>
      <h2>{headline}</h2>
      <ol className="steps">
        {steps.map((s, i) => (
          <li key={s.id} className={i < stageIdx ? "done" : i === stageIdx ? "active" : ""}>
            {s.label}
          </li>
        ))}
      </ol>
      {job.stage === "identifying" && job.samples_total > 0 && (
        <>
          <div className="bar">
            <div style={{ width: `${pct}%` }} />
          </div>
          <p className="muted">
            Listened to {job.samples_done} of {job.samples_total} samples · {pct}%
          </p>
        </>
      )}
      {job.stage === "downloading" && <p className="muted">Long sets take a minute to download.</p>}
    </div>
  );
}

function ResultView({ result, cached, onRedo }: { result: Result; cached: boolean; onRedo: () => void }) {
  const { info, entries } = result;
  const playerEl = useRef<HTMLDivElement>(null);
  const player = useRef<YTPlayer | null>(null);
  const [ready, setReady] = useState(false);
  const [playerError, setPlayerError] = useState<string | null>(null);
  const [now, setNow] = useState(0);
  const [preview, setPreview] = useState<{ i: number; key: number } | null>(null);
  const previewTimer = useRef<number>();
  const longSet = result.duration >= 3600;

  useEffect(() => {
    let cancelled = false;
    loadYouTubeApi()
      .then(() => {
        if (cancelled || !playerEl.current || !window.YT) return;
        player.current = new window.YT.Player(playerEl.current, {
          videoId: info.video_id,
          playerVars: { playsinline: 1, modestbranding: 1, rel: 0 },
          events: {
            onReady: () => setReady(true),
            onError: () => setPlayerError("This video can't be played here (the uploader may have disabled embedding)."),
          },
        });
      })
      .catch((e) => setPlayerError(e.message));
    return () => {
      cancelled = true;
      clearTimeout(previewTimer.current);
      player.current?.destroy();
      player.current = null;
    };
  }, [info.video_id]);

  useEffect(() => {
    if (!ready) return;
    const t = window.setInterval(() => {
      const p = player.current;
      if (p && typeof p.getCurrentTime === "function") setNow(p.getCurrentTime());
    }, 500);
    return () => clearInterval(t);
  }, [ready]);

  const currentIdx = useMemo(
    () => (now > 0 ? entries.findIndex((e) => now >= e.start && now < e.end) : -1),
    [entries, now],
  );

  const seek = (t: number) => {
    const p = player.current;
    if (!p || !ready) return;
    clearTimeout(previewTimer.current);
    setPreview(null);
    p.seekTo(t, true);
    p.playVideo();
  };

  const playDrop = (i: number) => {
    const p = player.current;
    const d = entries[i].drop;
    if (!p || !ready || !d) return;
    clearTimeout(previewTimer.current);
    if (preview?.i === i) {
      p.pauseVideo();
      setPreview(null);
      return;
    }
    p.seekTo(Math.max(0, d.time - LEAD_IN), true);
    p.playVideo();
    setPreview({ i, key: Date.now() });
    previewTimer.current = window.setTimeout(() => {
      p.pauseVideo();
      setPreview(null);
    }, PREVIEW_SECONDS * 1000);
  };

  const known = entries.filter((e) => e.title).length;
  const drops = entries.filter((e) => e.drop).length;

  return (
    <section className="result">
      <div className="player-wrap">
        <div className="player">
          <div ref={playerEl} />
          {playerError && <div className="player-error">{playerError}</div>}
        </div>
      </div>

      <div className="set-head">
        <div>
          <h2>{info.title}</h2>
          <p className="muted">
            {info.uploader && <>{info.uploader} · </>}
            {fmtTime(result.duration)} · {plural(known, "track")} identified
            {entries.length > known && <> · {entries.length - known} unknown</>} · {plural(drops, "drop")}
            {cached && <> · from cache</>}
          </p>
        </div>
        <ExportMenu result={result} onRedo={onRedo} />
      </div>

      {known === 0 && (
        <div className="card notice">
          No tracks could be identified in this set. That happens with unreleased IDs, heavy edits or non-music videos.
        </div>
      )}

      <ol className="tracks">
        {entries.map((e, i) => (
          <TrackRow
            key={i}
            n={i + 1}
            entry={e}
            longSet={longSet}
            current={i === currentIdx}
            previewKey={preview?.i === i ? preview.key : null}
            disabled={!ready}
            onSeek={() => seek(e.start)}
            onDrop={() => playDrop(i)}
          />
        ))}
      </ol>
    </section>
  );
}

function TrackRow(props: {
  n: number;
  entry: Entry;
  longSet: boolean;
  current: boolean;
  previewKey: number | null;
  disabled: boolean;
  onSeek: () => void;
  onDrop: () => void;
}) {
  const { entry: e, n, longSet, current, previewKey, disabled } = props;
  const unknown = !e.title;
  return (
    <li className={`track ${unknown ? "unknown" : ""} ${current ? "current" : ""}`}>
      <span className="num">{String(n).padStart(2, "0")}</span>
      <button className="ts" onClick={props.onSeek} disabled={disabled} title="Play from here">
        {fmtTime(e.start, longSet)}
      </button>
      <div className="meta">
        {e.extra?.cover ? <img className="cover" src={e.extra.cover} alt="" loading="lazy" /> : <div className="cover blank" />}
        <div className="names">
          <span className="title">
            {unknown ? "ID" : e.title}
            {e.uncertain && (
              <span className="badge" title="Only heard in one sample. Double-check this one.">
                ?
              </span>
            )}
          </span>
          <span className="artist">{unknown ? "Unknown track" : e.artist}</span>
        </div>
      </div>
      <div className="links">
        {e.links.spotify && (
          <a className="pill spotify" href={e.links.spotify} target="_blank" rel="noreferrer" aria-label={`Find ${e.title} on Spotify`}>
            Spotify
          </a>
        )}
        {e.links.soundcloud && (
          <a className="pill soundcloud" href={e.links.soundcloud} target="_blank" rel="noreferrer" aria-label={`Find ${e.title} on SoundCloud`}>
            SoundCloud
          </a>
        )}
      </div>
      <button
        className={`drop-btn ${previewKey ? "playing" : ""}`}
        onClick={props.onDrop}
        disabled={disabled || !e.drop}
        title={e.drop ? `Drop at ${fmtTime(e.drop.time, longSet)}` : "No clear drop found"}
      >
        {previewKey && <span key={previewKey} className="drop-progress" style={{ animationDuration: `${PREVIEW_SECONDS}s` }} />}
        <span className="drop-label">
          {previewKey ? <StopIcon /> : <PlayIcon />}
          {e.drop ? (previewKey ? "Stop" : "Play drop") : "No drop"}
        </span>
        {e.drop && !previewKey && <span className="drop-time">{fmtTime(e.drop.time, longSet)}</span>}
      </button>
    </li>
  );
}

function ExportMenu({ result, onRedo }: { result: Result; onRedo: () => void }) {
  const [copied, setCopied] = useState(false);
  const [withDrops, setWithDrops] = useState(false);
  const vid = result.info.video_id;

  const copy = async () => {
    const text = await fetch(api.exportUrl(vid, withDrops)).then((r) => r.text());
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
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="export">
      <label className="check">
        <input type="checkbox" checked={withDrops} onChange={(e) => setWithDrops(e.target.checked)} /> drop times
      </label>
      <button className="ghost" onClick={copy}>
        {copied ? "Copied!" : "Copy tracklist"}
      </button>
      <a className="ghost" href={api.exportUrl(vid, withDrops)} download>
        .txt
      </a>
      <button className="ghost subtle" onClick={onRedo} title="Process this set again from scratch (uses cached samples)">
        Re-run
      </button>
    </div>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

const Wave = () => (
  <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden>
    <path d="M3 18h4l2.5-8 3.5 15 3.5-19 3.5 13 2.5-5H29" stroke="currentColor" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const PlayIcon = () => (
  <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden>
    <path d="M4 2.5v11l9-5.5z" fill="currentColor" />
  </svg>
);
const StopIcon = () => (
  <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden>
    <rect x="3" y="3" width="10" height="10" rx="1.5" fill="currentColor" />
  </svg>
);
