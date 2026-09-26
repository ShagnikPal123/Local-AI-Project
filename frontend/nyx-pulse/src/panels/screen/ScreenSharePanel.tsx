/** Screen Share (Request R10): Nyx looks at what you share and helps, one step at a time, at your pace.
 *
 * "Another tab will be screen share so it views a persons screen and can help them using its cursor and typing. It
 * works with the user and at its pace. … Don't allow it to have too mc control and instead just work properly."
 *
 * The page decides nothing by itself: it shows the live picture, sends the owner's question and offers the one step
 * Nyx proposed, with buttons. The limits (Show Me only points, one approved step at a time, simple keys, no secrets,
 * steps expire, sharing stops when you leave) are enforced by the server in screen_share.py; the page explains them.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, authHeaders } from "../../api";
import { Icon } from "../../components/chat/Icon";
import "./screen.css";

type Pace = "show" | "ask";

interface Source {
  kind: "screen" | "window"; index?: number; hwnd?: number; label?: string; title?: string; process?: string;
  width?: number; height?: number; minimized?: boolean; focused?: boolean;
}
interface Step {
  id: string; kind: string; target: string; why: string; point: [number, number] | null; text: string; keys: string;
  amount: number; caution: boolean; blocked: string; hands_on: boolean; created: number; status: string; shown: boolean;
  expires_in: number;
}
interface Message {
  role: "you" | "nyx" | "action" | "note" | "error"; text: string; at: number; model?: string; local?: boolean;
  step_id?: string; ok?: boolean; done?: boolean;
}
interface ModelInfo {
  local: string; suggested: string; suggested_gb: number; ollama_installed: boolean; ollama_running: boolean; cloud: string;
}
interface ShareState {
  sharing: boolean; ended?: string; id?: string; source?: Source & { label: string }; pace?: Pace; allow_cloud?: boolean;
  goal?: string; messages?: Message[]; step?: Step | null; busy?: boolean; frames?: number; idle_stop_in?: number;
  model: ModelInfo; limits: { step_seconds: number; idle_minutes: number; max_type: number; keys: string[] };
}
interface Sources { screens: Source[]; windows: Source[] }

const QUICK = ["What am I looking at?", "Explain this code", "Check this formula", "Summarise this sheet", "What should I do next?"];

function stepTitle(step: Step): string {
  const target = step.target || "this spot";
  switch (step.kind) {
    case "click": return `Click ${target}`;
    case "double_click": return `Double-click ${target}`;
    case "type": return `Type into ${step.target || "the field"}`;
    case "keys": return `Press ${step.keys}`;
    case "scroll": return `Scroll ${step.amount < 0 ? "down" : "up"}${step.target ? ` in ${step.target}` : ""}`;
    default: return `Look at ${target}`;
  }
}

function openTab(tab: string) {
  window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab } }));
}

/** The live picture: fetched with the owner's token, decoded off-screen, then swapped in, so it never flickers. */
function useFrames(active: boolean): { url: string; error: string } {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!active) { setUrl(""); setError(""); return; }
    let alive = true;
    let current = "";
    let timer = 0;
    const tick = async () => {
      if (!alive) return;
      if (document.hidden) { timer = window.setTimeout(tick, 1200); return; }
      try {
        const response = await fetch("/api/screen/frame?max_width=1280", { headers: authHeaders(), cache: "no-store" });
        if (response.ok) {
          const next = URL.createObjectURL(await response.blob());
          const image = new Image();
          image.src = next;
          await image.decode().catch(() => undefined);
          if (!alive) { URL.revokeObjectURL(next); return; }
          const old = current;
          current = next;
          setUrl(next);
          setError("");
          if (old) window.setTimeout(() => URL.revokeObjectURL(old), 1500);
        } else {
          const body = await response.json().catch(() => null);
          setError(typeof body?.detail === "string" ? body.detail : `The picture did not arrive (${response.status}).`);
        }
      } catch {
        setError("Cannot reach the local backend.");
      }
      if (alive) timer = window.setTimeout(tick, 900);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
      if (current) window.setTimeout(() => URL.revokeObjectURL(current), 1500);
    };
  }, [active]);
  return { url, error };
}

export function ScreenSharePanel() {
  const [state, setState] = useState<ShareState | null>(null);
  const [error, setError] = useState("");
  const sharing = Boolean(state?.sharing);
  const sharingRef = useRef(false);
  sharingRef.current = sharing;

  const refresh = useCallback(async () => {
    const result = await api.get<ShareState>("/api/screen");
    if (result.ok) { setState(result.data); setError(""); }
    else setError(result.error);
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!sharing) return;
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 2500);
    return () => window.clearInterval(timer);
  }, [sharing, refresh]);
  // Leaving the tab stops sharing: nothing keeps looking at the screen behind the owner's back.
  useEffect(() => () => { if (sharingRef.current) void api.post("/api/screen/stop"); }, []);

  const stop = async () => {
    const result = await api.post<ShareState>("/api/screen/stop");
    if (result.ok) setState(result.data); else setError(result.error);
  };

  return (
    <div className="ss">
      <header className="ss-head">
        <div>
          <h1>Screen Share</h1>
          <p>Nyx looks at what you share and helps one step at a time. It acts only when you press a button.</p>
        </div>
        <div className="ss-head__right">
          <span className={`ss-status${sharing ? " is-on" : ""}`} role="status">
            <span className="ss-status__dot" aria-hidden="true" />
            {sharing ? `Sharing ${state?.source?.label ?? ""}` : "Not sharing"}
          </span>
          {sharing && <button className="ss-btn ss-btn--stop" onClick={() => void stop()}>Stop Sharing</button>}
        </div>
      </header>
      {error && <p className="ss-error" role="alert">{error}</p>}
      {!state ? <p className="ss-muted">Loading…</p>
        : sharing ? <LiveView state={state} onState={setState} />
        : <StartView state={state} onState={setState} />}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// Before sharing: what to share, how much Nyx may do, and who looks
// ---------------------------------------------------------------------------------------------------------------------

function StartView({ state, onState }: { state: ShareState; onState: (s: ShareState) => void }) {
  const [sources, setSources] = useState<Sources | null>(null);
  const [pick, setPick] = useState<Source | null>(null);
  const [pace, setPace] = useState<Pace>("show");
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<Sources>("/api/screen/sources");
    if (!result.ok) { setError(result.error); return; }
    setSources(result.data);
    setPick((current) => current ?? result.data.screens.find((s) => s.label?.includes("main")) ?? result.data.screens[0] ?? null);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const windows = useMemo(() => {
    const wanted = filter.trim().toLowerCase();
    return (sources?.windows ?? []).filter((w) => !wanted || `${w.title} ${w.process}`.toLowerCase().includes(wanted));
  }, [sources, filter]);

  const same = (a: Source | null, b: Source) => Boolean(a && a.kind === b.kind && (a.kind === "screen" ? a.index === b.index : a.hwnd === b.hwnd));

  const start = async () => {
    if (!pick) return;
    setBusy(true);
    const result = await api.post<ShareState>("/api/screen/start", { source: pick, pace });
    setBusy(false);
    if (result.ok) onState(result.data); else setError(result.error);
  };

  return (
    <div className="ss-start">
      {state.ended && <p className="ss-note">{state.ended}</p>}
      <section className="ss-card" aria-labelledby="ss-what">
        <div className="ss-card__head">
          <h2 id="ss-what">What to Share</h2>
          <button className="ss-link" onClick={() => void load()}>Refresh</button>
        </div>
        <div className="ss-sources" role="radiogroup" aria-label="Screens">
          {(sources?.screens ?? []).map((screen) => (
            <button key={`s${screen.index}`} role="radio" aria-checked={same(pick, screen)}
              className={`ss-source${same(pick, screen) ? " is-on" : ""}`} onClick={() => setPick(screen)}>
              <Icon name="monitor" size={22} />
              <span><b>{screen.label}</b><small>{screen.width}×{screen.height}</small></span>
            </button>
          ))}
        </div>
        <label className="ss-search">
          <span className="sr-only">Find a window</span>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Or pick one window…" />
        </label>
        <div className="ss-windows" role="radiogroup" aria-label="Windows">
          {windows.map((window) => (
            <button key={`w${window.hwnd}`} role="radio" aria-checked={same(pick, window)} disabled={window.minimized}
              className={`ss-window${same(pick, window) ? " is-on" : ""}`} onClick={() => setPick(window)}
              title={window.minimized ? "Minimised: restore it to share it" : window.title}>
              <span className="ss-window__title">{window.title}</span>
              <small>{window.process}{window.minimized ? " · minimised" : ""}</small>
            </button>
          ))}
          {sources && windows.length === 0 && <p className="ss-muted">No windows match.</p>}
        </div>
        <p className="ss-hint">A single window works best: Nyx sees it even when the Nyx window is in front, and it
          gets the whole picture to itself. Put Nyx beside it (Win + ← or →) to keep both in view.</p>
      </section>

      <section className="ss-card" aria-labelledby="ss-how">
        <h2 id="ss-how">How Much Nyx Does</h2>
        <PacePicker value={pace} onChange={setPace} />
        <ul className="ss-rules">
          <li>Nothing is seen until you press Start Sharing, and pictures are never saved.</li>
          <li>Nyx proposes one step at a time. It expires after two minutes.</li>
          <li>Keys are limited to simple ones like Enter, Tab, arrows and Ctrl+C/V/Z/S.</li>
          <li>It never types passwords, codes or card numbers.</li>
          <li>Stop anything: move your mouse to the top-left corner or press Esc three times.</li>
        </ul>
      </section>

      <section className="ss-card" aria-labelledby="ss-who">
        <h2 id="ss-who">Who Looks</h2>
        <WhoLooks model={state.model} />
      </section>

      <div className="ss-start__go">
        {error && <p className="ss-error" role="alert">{error}</p>}
        <button className="ss-btn ss-btn--primary" disabled={!pick || busy} onClick={() => void start()}>
          {busy ? "Starting…" : "Start Sharing"}
        </button>
      </div>
    </div>
  );
}

function PacePicker({ value, onChange, compact = false }: { value: Pace; onChange: (p: Pace) => void; compact?: boolean }) {
  return (
    <div className={`ss-pace${compact ? " is-compact" : ""}`}>
      <div className="ss-seg" role="radiogroup" aria-label="How much Nyx does">
        <button role="radio" aria-checked={value === "show"} className={value === "show" ? "is-on" : ""} onClick={() => onChange("show")}>
          Show Me
        </button>
        <button role="radio" aria-checked={value === "ask"} className={value === "ask" ? "is-on" : ""} onClick={() => onChange("ask")}>
          Ask First
        </button>
      </div>
      {!compact && (
        <p className="ss-muted">
          {value === "show"
            ? "Nyx points with its own purple cursor and tells you what to click or type. Your mouse and keyboard stay yours."
            : "Nyx may click, type, press a simple key or scroll: one step, and only after you press Do It."}
        </p>
      )}
    </div>
  );
}

function WhoLooks({ model }: { model: ModelInfo }) {
  const [pulling, setPulling] = useState("");
  if (model.local) {
    return <p className="ss-good"><Icon name="shield" size={18} /> {model.local} on this PC. Pictures never leave this computer.</p>;
  }
  const pull = async () => {
    setPulling("Starting the download…");
    const result = await api.post<unknown>("/api/local-models/pull", { name: model.suggested });
    setPulling(result.ok ? `Downloading ${model.suggested}. Follow it in Keys → Local models.` : result.error);
  };
  return (
    <div className="ss-who">
      <p>No vision model on this PC yet. Screen Share is built for a local one: {model.suggested} ({model.suggested_gb} GB)
        reads screens well and fits this PC's graphics card.</p>
      <div className="ss-row">
        {model.ollama_running
          ? <button className="ss-btn" onClick={() => void pull()} disabled={Boolean(pulling)}>Get {model.suggested}</button>
          : <button className="ss-btn" onClick={() => openTab("keys")}>{model.ollama_installed ? "Start Ollama in Keys" : "Set Up Ollama in Keys"}</button>}
      </div>
      {pulling && <p className="ss-muted" role="status">{pulling}</p>}
      {model.cloud && <p className="ss-muted">Until then, Nyx can look with {model.cloud} online. You will be asked
        before any picture is sent.</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// While sharing: the picture, the conversation, and the one step waiting
// ---------------------------------------------------------------------------------------------------------------------

function LiveView({ state, onState }: { state: ShareState; onState: (s: ShareState) => void }) {
  const { url, error: frameError } = useFrames(true);
  const [question, setQuestion] = useState("");
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [needsCloud, setNeedsCloud] = useState(false);
  const log = useRef<HTMLOListElement>(null);
  const step = state.step ?? null;
  const pace = state.pace ?? "show";
  const messages = state.messages ?? [];
  const cloudBlocked = !state.model.local && !state.allow_cloud;

  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" }); }, [messages.length]);

  const run = async (label: string, call: () => Promise<{ ok: true; data: ShareState } | { ok: false; error: string; status?: number }>) => {
    setWorking(label);
    setError("");
    const result = await call();
    setWorking("");
    if (result.ok) { onState(result.data); return true; }
    if (result.status === 409 && /vision model on this PC/.test(result.error)) setNeedsCloud(true);
    else setError(result.error);
    return false;
  };

  const ask = async (text: string, next = false) => {
    const clean = text.trim();
    if (!clean && !next) return;
    if (cloudBlocked) { setNeedsCloud(true); return; }
    const ok = await run("Looking…", () => api.post<ShareState>("/api/screen/ask", { question: clean, next }, 200_000));
    if (ok && !next) setQuestion("");
  };
  const act = (action: "show" | "do" | "mine" | "skip") => {
    if (!step) return;
    void run(action === "do" ? "Doing it…" : action === "show" ? "Pointing…" : "…",
      () => api.post<ShareState>(`/api/screen/steps/${step.id}/${action}`)).then((ok) => {
      if (ok && (action === "do" || action === "mine")) void ask("", true);   // the owner moved on: look again
    });
  };
  const setPace = (next: Pace) => void run("", () => api.post<ShareState>("/api/screen/pace", { pace: next }));
  const allowCloud = async () => {
    const ok = await run("", () => api.post<ShareState>("/api/screen/cloud", { allow: true }));
    if (ok) setNeedsCloud(false);
  };

  const last = messages[messages.length - 1];
  const canNext = !step && Boolean(state.goal) && last && (last.role === "action" || last.role === "nyx");

  return (
    <div className="ss-live">
      <section className="ss-view" aria-label="What Nyx can see">
        <div className="ss-view__bar">
          <PacePicker value={pace} onChange={setPace} compact />
          <span className="ss-muted">Stop anything: mouse to the top-left corner, or Esc three times.</span>
        </div>
        <div className="ss-stage">
          {url ? (
            <div className="ss-frame">
              <img src={url} alt={`Live picture of ${state.source?.label ?? "what you share"}`} />
              {step?.point && (
                <span className={`ss-marker${step.caution ? " is-caution" : ""}`} aria-hidden="true"
                  style={{ left: `${step.point[0] * 100}%`, top: `${step.point[1] * 100}%` }} />
              )}
            </div>
          ) : <p className="ss-muted">{frameError || "Waiting for the first picture…"}</p>}
        </div>
      </section>

      <section className="ss-talk" aria-label="Talk about the screen">
        {(cloudBlocked && (needsCloud || messages.length <= 1)) && (
          <div className="ss-consent" role="dialog" aria-labelledby="ss-consent-title">
            <h3 id="ss-consent-title">Nyx Has No Vision Model on This PC</h3>
            <p>To answer, it would send one picture of {state.source?.label ?? "what you share"} to {state.model.cloud || "the online model"} each
              time you ask. Nothing is sent until you allow it, and it only lasts for this session.</p>
            <div className="ss-row">
              <button className="ss-btn ss-btn--primary" onClick={() => void allowCloud()}>Allow for This Session</button>
              <button className="ss-btn" onClick={() => openTab("keys")}>Get a Local Model</button>
            </div>
          </div>
        )}

        <ol className="ss-log" ref={log} aria-live="polite">
          {messages.map((message, index) => (
            <li key={index} className={`ss-msg is-${message.role}`}>
              {message.role === "nyx" && message.model && (
                <span className="ss-msg__model">{message.model}{message.local ? "" : " · online"}</span>
              )}
              <p>{message.text}</p>
            </li>
          ))}
          {working === "Looking…" && <li className="ss-msg is-nyx is-thinking"><p>Looking at the screen…</p></li>}
        </ol>

        {step && <StepCard step={step} pace={pace} working={Boolean(working)} onAct={act} />}

        {error && <p className="ss-error" role="alert">{error}</p>}
        <div className="ss-quick">
          {canNext && <button className="ss-chip is-next" onClick={() => void ask("", true)} disabled={Boolean(working)}>Next Step</button>}
          {QUICK.map((text) => (
            <button key={text} className="ss-chip" onClick={() => void ask(text)} disabled={Boolean(working)}>{text}</button>
          ))}
        </div>
        <form className="ss-compose" onSubmit={(e) => { e.preventDefault(); void ask(question); }}>
          <label className="sr-only" htmlFor="ss-question">Ask about the screen</label>
          <textarea id="ss-question" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about what you are sharing: this code, this sheet, this form…"
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(question); } }} />
          <button className="ss-btn ss-btn--primary" type="submit" disabled={!question.trim() || Boolean(working)}>
            {working === "Looking…" ? "Looking…" : "Ask"}
          </button>
        </form>
      </section>
    </div>
  );
}

function StepCard({ step, pace, working, onAct }: {
  step: Step; pace: Pace; working: boolean; onAct: (action: "show" | "do" | "mine" | "skip") => void;
}) {
  const [copied, setCopied] = useState(false);
  const [left, setLeft] = useState(step.expires_in);
  useEffect(() => {
    setLeft(step.expires_in);
    const timer = window.setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [step.id, step.expires_in]);
  const canDo = pace === "ask" && !step.blocked && step.kind !== "point";
  const copy = async () => {
    try { await navigator.clipboard.writeText(step.text || step.keys); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }
    catch { /* the clipboard said no */ }
  };
  return (
    <div className={`ss-step${step.caution ? " is-caution" : ""}${step.blocked ? " is-blocked" : ""}`} aria-label="The next step">
      <div className="ss-step__head">
        <span className="ss-step__eyebrow">Next Step</span>
        <span className="ss-muted">{left > 0 ? `expires in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : "expired: ask again"}</span>
      </div>
      <h3>{stepTitle(step)}</h3>
      {step.why && <p className="ss-step__why">{step.why}</p>}
      {step.kind === "type" && step.text && <pre className="ss-step__text">{step.text}</pre>}
      {step.caution && <p className="ss-step__caution">This may not be undoable. Check before going ahead.</p>}
      {step.blocked && <p className="ss-step__blocked">{step.blocked}</p>}
      {step.hands_on && !step.blocked && <p className="ss-muted">You do this one. Nyx is on Show Me.</p>}
      <div className="ss-row">
        {step.point && <button className="ss-btn" onClick={() => onAct("show")} disabled={working || left === 0}>Show Me</button>}
        {canDo && (
          <button className={`ss-btn ${step.caution ? "ss-btn--danger" : "ss-btn--primary"}`} onClick={() => onAct("do")}
            disabled={working || left === 0}>Do It</button>
        )}
        {(step.kind === "type" || step.kind === "keys") && (
          <button className="ss-btn" onClick={() => void copy()}>{copied ? "Copied" : step.kind === "type" ? "Copy Text" : "Copy Keys"}</button>
        )}
        {!canDo && <button className="ss-btn ss-btn--primary" onClick={() => onAct("mine")} disabled={working}>I Did It</button>}
        <button className="ss-btn ss-btn--plain" onClick={() => onAct("skip")} disabled={working}>Skip</button>
      </div>
    </div>
  );
}
