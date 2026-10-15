/** Equalize — the assistant in the notch, and its setup (owner, 2026-10-11: "forget everything we have in there so
 * far"; verbatim in AI_HANDOFF/01_GOALS.md).
 *
 * The page starts with the notch itself, live, over a little desktop — the same component the desktop window shows —
 * with a switch to put it on the real screen. Below it, in the order the owner described: do you want to talk to it
 * at all; the gesture that wakes it (claps, a snap, a phrase…); its voice (describe it, drop a voice file, or record
 * one); its personality; an avatar to drop in (which brings its own personality — keep it or stay normal); the agents
 * you can drag into the notch and hand tasks to; the apps pinned to the left notch; and Ultra Fast (Jev's way). */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, authHeaders, uploadFile } from "../../api";
import { startClapListening, startTeaching, stopTeaching } from "../../voice/clapDetector";
import { Notch } from "../../notch/Notch";
import { notchApi, type AssistantSettings, type CatalogAgent, type NotchAgent } from "../../notch/notchApi";
import { MiniIo } from "../../notch/IoView";
import "./equalize.css";
import { NotchControlsCard } from "./NotchControlsCard";
import { NotchLooksCard } from "./NotchLooksCard";

const GESTURE_ORDER = ["clap", "snap", "whistle", "phrase", "knock", "hotkey", "hover"];
const GESTURE_NAMES: Record<string, string> = { clap: "Clap twice", snap: "Finger snap", whistle: "Whistle",
  phrase: "Wake phrase", knock: "Knock", hotkey: "Shortcut", hover: "Top of screen" };
const APP_PRESETS = [
  { name: "GitHub", kind: "github", hint: "A repo folder on this PC or owner/repo" },
  { name: "VS Code", kind: "vscode", hint: "A project folder" },
  { name: "Vercel", kind: "vercel", hint: "A project name" },
  { name: "Gmail", kind: "gmail", hint: "An address" },
  { name: "Custom", kind: "app", hint: "What it is" },
];

/** The fundamental pitch of a voice sample, by autocorrelation — enough to pick a matching voice. */
async function pitchOf(blob: Blob): Promise<{ hz: number; seconds: number }> {
  const ctx = new AudioContext();
  try {
    const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
    const data = audio.getChannelData(0);
    const rate = audio.sampleRate;
    const found: number[] = [];
    const size = 2048;
    for (let start = 0; start + size < data.length && found.length < 60; start += Math.floor(rate / 8)) {
      const frame = data.subarray(start, start + size);
      let energy = 0;
      for (const v of frame) energy += v * v;
      if (energy / size < 0.0004) continue;
      let best = 0, bestLag = 0;
      for (let lag = Math.floor(rate / 400); lag < Math.floor(rate / 60); lag++) {
        let sum = 0;
        for (let i = 0; i < size - lag; i++) sum += frame[i] * frame[i + lag];
        if (sum > best) { best = sum; bestLag = lag; }
      }
      if (bestLag) found.push(rate / bestLag);
    }
    found.sort((a, b) => a - b);
    return { hz: found.length ? found[Math.floor(found.length / 2)] : 0, seconds: audio.duration };
  } finally {
    void ctx.close();
  }
}

export function EqualizePanel() {
  const [settings, setSettings] = useState<AssistantSettings | null>(null);
  const [agents, setAgents] = useState<NotchAgent[]>([]);
  const [catalog, setCatalog] = useState<CatalogAgent[]>([]);
  const [onDesktop, setOnDesktop] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const [state, list, notch] = await Promise.all([notchApi.state(), notchApi.agents(),
      api.get<{ running: boolean }>("/api/notch")]);
    if (state.ok) { setSettings(state.data.settings); setAgents(state.data.agents); }
    if (list.ok) setCatalog(list.data.catalog);
    if (notch.ok) setOnDesktop(notch.data.running);
  }, []);
  useEffect(() => {
    void load();
    const id = window.setInterval(load, 5000);
    return () => window.clearInterval(id);
  }, [load]);

  const save = async (changes: Partial<AssistantSettings>) => {
    setSettings((s) => (s ? ({ ...s, ...changes } as AssistantSettings) : s));
    const result = await notchApi.save(changes);
    if (result.ok) {
      setSettings(result.data);
      window.dispatchEvent(new CustomEvent("nyx:equalize-changed"));   // the ear (ClapListener) re-reads how to wake
    } else setMessage(result.error);
  };

  const toggleDesktop = async () => {
    const result = await api.post<{ running: boolean }>(onDesktop ? "/api/notch/stop" : "/api/notch/start");
    if (result.ok) setOnDesktop(result.data.running);
    else setMessage(result.error);
  };

  if (!settings) return <div className="eq"><p className="eq-muted">Loading Equalize…</p></div>;
  const s = settings;

  return (
    <div className="eq">
      <section className="eq-stage">
        <Notch embedded />
        <div className="eq-stage-bar">
          <div>
            <h1>Equalize</h1>
            <p className="eq-muted">Ichos in the notch. Rest the pointer on it, drop a file on it, drag an agent into it.</p>
          </div>
          <label className="eq-switch-row">
            <span>Show on my desktop</span>
            <button className={`eq-switch ${onDesktop ? "on" : ""}`} onClick={() => void toggleDesktop()} role="switch" aria-checked={onDesktop} />
          </label>
        </div>
        {message ? <p className="eq-error" role="alert">{message}</p> : null}
      </section>

      <div className="eq-grid" id="eq-setup">
        <TalkCard settings={s} save={save} />
        <WakeCard settings={s} save={save} />
        <VoiceCard settings={s} onSaved={(voice) => setSettings({ ...s, voice })} />
        <PersonalityCard settings={s} save={save} />
        <AvatarCard settings={s} catalog={catalog} onSaved={setSettings} />
        <AgentsCard agents={agents} catalog={catalog} onChange={load} />
        <PinnedCard settings={s} save={save} />
        <UltraCard settings={s} save={save} />
        <NotchControlsCard />
        <NotchLooksCard />
      </div>
    </div>
  );
}

type CardProps = { settings: AssistantSettings; save: (changes: Partial<AssistantSettings>) => Promise<void> };

function Card({ title, sub, children, wide }: { title: string; sub?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <section className={`eq-card ${wide ? "wide" : ""}`}>
      <h2>{title}{sub ? <span>{sub}</span> : null}</h2>
      {children}
    </section>
  );
}

function TalkCard({ settings, save }: CardProps) {
  return (
    <Card title="1 · Talk to it?" sub="You can always type">
      <div className="eq-choice">
        <button className={settings.talk ? "on" : ""} onClick={() => void save({ talk: true })}>
          <b>Yes, out loud</b><span>It listens when you wake it, and answers with its voice.</span></button>
        <button className={!settings.talk ? "on" : ""} onClick={() => void save({ talk: false })}>
          <b>No, just type</b><span>The notch stays quiet; you chat in it.</span></button>
      </div>
    </Card>
  );
}

function WakeCard({ settings, save }: CardProps) {
  const [teaching, setTeaching] = useState("");
  const act = settings.activation;
  const toggle = (g: string) => {
    const on = act.gestures.includes(g);
    void save({ activation: { ...act, gestures: on ? act.gestures.filter((x) => x !== g) : [...act.gestures, g] } });
  };
  const teach = async (kind: string) => {
    if (!(await startClapListening())) { setTeaching("The microphone is blocked — allow it for this page."); return; }
    setTeaching(`Listening — ${kind === "snap" ? "snap your fingers" : "knock"} now…`);
    startTeaching();
    window.setTimeout(async () => {
      const template = stopTeaching();
      if (!template.length) { setTeaching("Didn't hear it — try again a little louder."); return; }
      const result = await api.post("/api/voice/gestures", { name: GESTURE_NAMES[kind], kind: "taught", action: "listen",
        when: ["always"], say: "", template });
      setTeaching(result.ok ? `Learned your ${GESTURE_NAMES[kind].toLowerCase()}.` : result.error);
      if (result.ok && !act.gestures.includes(kind)) toggle(kind);
    }, 2500);
  };
  return (
    <Card title="2 · Wake it up" sub="Any of these starts it listening">
      <p className="eq-muted">Pick what you'd like to use. Sounds are recognised on this PC from their shape — nothing is
        recorded or sent anywhere. A snap or a knock is taught once so it knows yours; a phrase is any words you choose.</p>
      <div className="eq-gestures">
        {GESTURE_ORDER.map((g) => (
          <div key={g} className={`eq-gesture ${act.gestures.includes(g) ? "on" : ""}`}>
            <button className="eq-gesture-main" onClick={() => toggle(g)} aria-pressed={act.gestures.includes(g)}>
              <b>{GESTURE_NAMES[g]}</b><span>{settings.gesture_help[g]}</span>
            </button>
            {(g === "snap" || g === "knock") && <button className="eq-btn small" onClick={() => void teach(g)}>Teach it</button>}
          </div>
        ))}
      </div>
      {act.gestures.includes("phrase") && (
        <label className="eq-field"><span>Wake phrase</span>
          <input value={act.phrase} placeholder="e.g. hey Io" onChange={(e) => void save({ activation: { ...act, phrase: e.target.value } })} /></label>
      )}
      {act.gestures.includes("phrase") && (
        <p className="eq-muted">In the app window or offline, the phrase is heard on this PC (Windows dictation, or Whisper
          once installed); in Chrome or Edge, by the browser. Claps and whistles always work offline.</p>
      )}
      <label className="eq-field"><span>Sensitivity</span>
        <input type="range" min={10} max={100} value={Math.round(act.sensitivity * 100)}
          onChange={(e) => void save({ activation: { ...act, sensitivity: Number(e.target.value) / 100 } })} /></label>
      {teaching ? <p className="eq-muted" role="status">{teaching}</p> : null}
    </Card>
  );
}

function VoiceCard({ settings, onSaved }: { settings: AssistantSettings; onSaved: (v: AssistantSettings["voice"]) => void }) {
  const [description, setDescription] = useState(settings.voice.description);
  const [busy, setBusy] = useState("");
  const [recording, setRecording] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const v = settings.voice;

  const fromSample = async (blob: Blob, name: string, mode: "file" | "recorded") => {
    setBusy("Listening to the sample…");
    const { hz, seconds } = await pitchOf(blob).catch(() => ({ hz: 0, seconds: 0 }));
    const file = new File([blob], name, { type: blob.type || "audio/webm" });
    const upload = await uploadFile(file);
    const result = await notchApi.voice({ mode, description, sample: { pitch_hz: hz, seconds, name,
      upload_id: upload.ok ? upload.data.id : "" } });
    setBusy("");
    if (result.ok) onSaved(result.data);
  };
  const record = async () => {
    if (recording) { recorder.current?.stop(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const r = new MediaRecorder(stream);
      r.ondataavailable = (e) => chunks.push(e.data);
      r.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        void fromSample(new Blob(chunks, { type: r.mimeType }), "recording.webm", "recorded");
      };
      recorder.current = r;
      r.start();
      setRecording(true);
      window.setTimeout(() => { if (r.state === "recording") r.stop(); }, 8000);
    } catch {
      setBusy("The microphone is blocked — allow it for this page.");
    }
  };
  const hear = async () => {
    const response = await fetch("/api/voice/tts", { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ text: "Hi, I'm Io. This is how I'll sound.", voice: v.voice_id, rate: v.rate, pitch: v.pitch, role: "sample" }) });
    if (response.ok) void new Audio(URL.createObjectURL(await response.blob())).play();
  };
  return (
    <Card title="3 · Its voice" sub={v.name ? `Now: ${v.name} ${v.rate} ${v.pitch}` : "Now: the default voice"}>
      <label className="eq-field"><span>Describe it</span>
        <input value={description} placeholder="e.g. a calm, warm British woman, a little slow"
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void notchApi.voice({ mode: "described", description }).then((r) => r.ok && onSaved(r.data)); }} />
        <button className="eq-btn" onClick={() => void notchApi.voice({ mode: "described", description }).then((r) => r.ok && onSaved(r.data))}>Use this</button>
      </label>
      <div className="eq-row">
        <label className="eq-drop" onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) void fromSample(f, f.name, "file"); }}>
          <input type="file" accept="audio/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void fromSample(f, f.name, "file"); }} />
          Drop a voice file here, or click to pick one
        </label>
        <button className={`eq-btn ${recording ? "rec" : ""}`} onClick={() => void record()}>{recording ? "Stop recording" : "Record a voice"}</button>
        <button className="eq-btn" onClick={() => void hear()}>Hear it</button>
      </div>
      {v.sample ? <p className="eq-muted">Matched to “{v.sample.name}” ({Math.round(v.sample.pitch_hz)} Hz). Exact voice cloning needs a
        cloning engine, which isn't installed — the closest voice is used.</p> : null}
      {busy ? <p className="eq-muted" role="status">{busy}</p> : null}
    </Card>
  );
}

function PersonalityCard({ settings, save }: CardProps) {
  const p = settings.personality;
  const [text, setText] = useState(p.text);
  return (
    <Card title="4 · Personality">
      <div className="eq-seg">
        <button className={p.source === "normal" ? "on" : ""} onClick={() => void save({ personality: { ...p, source: "normal" } })}>Normal Ichos</button>
        <button className={p.source === "custom" ? "on" : ""} onClick={() => void save({ personality: { source: "custom", text } })}>My own words</button>
        <button className={p.source === "avatar" ? "on" : ""} disabled={!settings.avatar.personality}
          onClick={() => void save({ personality: { ...p, source: "avatar" } })}>The avatar's</button>
      </div>
      <textarea className="eq-area" value={text} placeholder="Say how it should be — e.g. dry humour, very short answers, encouraging when I'm stuck."
        onChange={(e) => setText(e.target.value)} onBlur={() => { if (text !== p.text) void save({ personality: { source: "custom", text } }); }} />
    </Card>
  );
}

function AvatarCard({ settings, catalog, onSaved }: { settings: AssistantSettings; catalog: CatalogAgent[]; onSaved: (s: AssistantSettings) => void }) {
  const a = settings.avatar;
  const [hot, setHot] = useState(false);
  const apply = async (body: Record<string, unknown>) => {
    const result = await notchApi.avatar(body);
    if (result.ok) onSaved(result.data);
  };
  const takeImage = async (file: File) => {
    const upload = await uploadFile(file);
    if (upload.ok) await apply({ image: upload.data.id, name: file.name.replace(/\.[^.]+$/, "").slice(0, 24) });
  };
  return (
    <Card title="5 · Avatar" sub="Drop a picture, or drag one of your avatars here">
      <div className={`eq-avatar ${hot ? "hot" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setHot(true); }} onDragLeave={() => setHot(false)}
        onDrop={(e) => {
          e.preventDefault();
          setHot(false);
          const agent = e.dataTransfer.getData("application/x-ichos-agent");
          if (agent.startsWith("avatar:")) void apply({ avatar_id: agent });
          else if (e.dataTransfer.files[0]) void takeImage(e.dataTransfer.files[0]);
        }}>
        {a.image ? <img src={`/api/uploads/${a.image}`} alt={a.name} /> : <MiniIo color="#A594FF" size={48} />}
        <div className="eq-grow">
          <b>{a.name}</b>
          <p className="eq-muted">{a.personality || "Io — Ichos's own character. Drop an avatar to change who's in the notch."}</p>
        </div>
        {(a.image || a.id) && <button className="eq-btn small" onClick={() => void apply({ reset: true })}>Back to Io</button>}
      </div>
      {a.personality ? (
        <div className="eq-choice small">
          <button className={a.keep_personality ? "on" : ""} onClick={() => void apply({ keep_personality: true })}>
            <b>Keep its personality</b></button>
          <button className={!a.keep_personality ? "on" : ""} onClick={() => void apply({ keep_personality: false })}>
            <b>Keep the normal one</b></button>
        </div>
      ) : null}
      <div className="eq-chips">
        {catalog.filter((c) => c.kind === "avatar").map((c) => (
          <button key={c.id} className="eq-chip" draggable onDragStart={(e) => e.dataTransfer.setData("application/x-ichos-agent", c.id)}
            onClick={() => void apply({ avatar_id: c.id })} title={c.personality}>
            <MiniIo color={c.color} size={16} />{c.name}</button>
        ))}
      </div>
    </Card>
  );
}

function AgentsCard({ agents, catalog, onChange }: { agents: NotchAgent[]; catalog: CatalogAgent[]; onChange: () => void }) {
  const [who, setWho] = useState("claude");
  const [task, setTask] = useState("");
  const [newName, setNewName] = useState("");
  const [note, setNote] = useState("");
  const start = async () => {
    if (!task.trim()) return;
    const result = await notchApi.task({ agent: who, task: task.trim(), new_name: who === "__new" ? newName : "" });
    setNote(result.ok ? `${result.data.agent?.name ?? "The agent"} is on it — watch it in the notch.` : result.error);
    if (result.ok) { setTask(""); onChange(); }
  };
  return (
    <Card title="6 · Agents" sub="Drag one into the notch; pick one and give it a task" wide>
      <div className="eq-chips">
        {catalog.map((c) => (
          <button key={c.id} className={`eq-chip ${who === c.id ? "on" : ""}`} draggable
            onDragStart={(e) => e.dataTransfer.setData("application/x-ichos-agent", c.id)} onClick={() => setWho(c.id)} title={c.about}>
            <MiniIo color={c.color} size={16} />{c.name}</button>
        ))}
        <button className={`eq-chip ${who === "__new" ? "on" : ""}`} onClick={() => setWho("__new")}>+ New agent</button>
      </div>
      <div className="eq-row">
        {who === "__new" && <input className="eq-input" style={{ maxWidth: 180 }} placeholder="Its name" value={newName} onChange={(e) => setNewName(e.target.value)} />}
        <input className="eq-input" placeholder={who === "claude" ? "e.g. fix the failing test in routes_equalize.py" : "What should it do?"}
          value={task} onChange={(e) => setTask(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void start(); }} />
        <button className="eq-btn primary" onClick={() => void start()} disabled={!task.trim() || (who === "__new" && !newName.trim())}>Start</button>
      </div>
      {note ? <p className="eq-muted" role="status">{note}</p> : null}
      <ul className="eq-list">
        {agents.filter((a) => a.id !== "ichos").map((a) => (
          <li key={a.id}><MiniIo color={a.color} size={18} state={a.state === "working" ? "working" : "idle"} />
            <b>{a.name}</b><span className={`eq-state is-${a.state}`}>{a.state}</span><span className="eq-muted eq-grow">{a.step}</span>
            <button className="eq-btn small" onClick={() => void notchApi.drop(a.id, true).then(onChange)}>Remove</button></li>
        ))}
      </ul>
    </Card>
  );
}

function PinnedCard({ settings, save }: CardProps) {
  const [kind, setKind] = useState("github");
  const [target, setTarget] = useState("");
  const preset = APP_PRESETS.find((p) => p.kind === kind) ?? APP_PRESETS[0];
  const add = () => {
    const name = kind === "app" ? target || "App" : preset.name;
    void save({ pinned: [...settings.pinned, { id: "", name, kind, target, color: "" }] });
    setTarget("");
  };
  return (
    <Card title="7 · Apps on the left notch" sub="Up to four; click one in the notch and say what to do with it">
      <div className="eq-row">
        <select className="eq-input" style={{ maxWidth: 130 }} value={kind} onChange={(e) => setKind(e.target.value)} aria-label="App">
          {APP_PRESETS.map((p) => <option key={p.kind} value={p.kind}>{p.name}</option>)}
        </select>
        <input className="eq-input" placeholder={preset.hint} value={target} onChange={(e) => setTarget(e.target.value)} />
        <button className="eq-btn" onClick={add} disabled={settings.pinned.length >= 4}>Pin</button>
      </div>
      <ul className="eq-list">
        {settings.pinned.map((p) => (
          <li key={p.id}><MiniIo color={p.color} size={18} /><b>{p.name}</b><span className="eq-muted eq-grow">{p.target}</span>
            <button className="eq-btn small" onClick={() => void save({ pinned: settings.pinned.filter((x) => x.id !== p.id) })}>Unpin</button></li>
        ))}
      </ul>
    </Card>
  );
}

function UltraCard({ settings, save }: CardProps) {
  const [status, setStatus] = useState<{ jev: boolean; recent: { text: string; reply: string; ms: number; via: string }[] } | null>(null);
  const [text, setText] = useState("");
  const [result, setResult] = useState("");
  useEffect(() => { void api.get<typeof status>("/api/ultrafast").then((r) => r.ok && setStatus(r.data)); }, []);
  const tryIt = async (dry: boolean) => {
    const r = await api.post<{ handled: boolean; reply: string; ms: number; plan: { action: string; via: string } }>("/api/ultrafast", { text, dry_run: dry });
    setResult(r.ok ? (r.data.handled ? `${r.data.plan.action ?? "done"} → ${r.data.reply} (${r.data.ms} ms${dry ? ", not done" : ""})`
      : `Not a desktop command — it goes to the chat (${r.data.ms} ms)`) : r.error);
  };
  return (
    <Card title="8 · Ultra Fast" sub="Based on Jev — commands decided in one step">
      <label className="eq-switch-row"><span>Use Ultra Fast in the notch, for spoken commands and as a chat mode</span>
        <button className={`eq-switch ${settings.ultrafast ? "on" : ""}`} role="switch" aria-checked={settings.ultrafast}
          onClick={() => void save({ ultrafast: !settings.ultrafast })} /></label>
      <p className="eq-muted">{status?.jev ? "Jev (TypeSafe) is connected — one ~250 ms request per command."
        : "Running locally (no key needed, ~1 ms). Add TYPESAFE_API_KEY in Keys to use Jev itself."}</p>
      <div className="eq-row">
        <input className="eq-input" placeholder="e.g. open notepad and type buy milk" value={text} onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void tryIt(true); }} />
        <button className="eq-btn" onClick={() => void tryIt(true)} disabled={!text.trim()}>Check</button>
        <button className="eq-btn primary" onClick={() => void tryIt(false)} disabled={!text.trim()}>Do it</button>
      </div>
      {result ? <p className="eq-muted" role="status">{result}</p> : null}
    </Card>
  );
}
