/** Start a study run: on its own, only what you give it, or a subject (Request R2–R4). */

import { useRef, useState } from "react";
import { api, uploadFile } from "../../api";
import type { Live, Mode, Overview, Settings } from "./types";

interface PendingFile { key: string; name: string; size: number; id?: string; error?: string }

const MODES: { id: Mode; title: string; body: string }[] = [
  { id: "auto", title: "On its own", body: "Nyx picks topics from what you talk about and where its memory is thin, then pulls papers, GitHub projects, Wikipedia and web pages." },
  { id: "given", title: "Only what I give", body: "Files and links you add — any mix. Nyx reads those and nothing else, and finds the topics inside them." },
  { id: "prompt", title: "Study a subject", body: "Say what to learn. Nyx plans the sub-topics, searches for exactly that and follows what it finds." },
];

const SOURCE_LABELS: Record<string, string> = { papers: "Research papers", github: "GitHub projects", wiki: "Wikipedia", web: "Web pages" };

export function StudyStart({ overview, onStarted }: { overview: Overview; onStarted: (live: Live) => void }) {
  const [mode, setMode] = useState<Mode>("auto");
  const [prompt, setPrompt] = useState("");
  const [links, setLinks] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [settings, setSettings] = useState<Settings>(overview.defaults);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const limit = (key: string): [number, number] => overview.limits[key] ?? [0, 100];

  const addFiles = async (list: File[]) => {
    for (const file of list) {
      const key = `${file.name}-${file.size}-${Math.random()}`;
      setFiles((current) => [...current, { key, name: file.name, size: file.size }]);
      const result = await uploadFile(file);
      setFiles((current) => current.map((f) => (f.key === key ? (result.ok ? { ...f, id: result.data.id } : { ...f, error: result.error }) : f)));
    }
  };

  const linkList = links.split(/\s+/).map((l) => l.trim()).filter(Boolean);
  const readyFiles = files.filter((f) => f.id);
  const uploading = files.some((f) => !f.id && !f.error);
  const canStart = !busy && !uploading && (mode === "auto" || (mode === "prompt" && prompt.trim().length >= 3) || (mode === "given" && (linkList.length > 0 || readyFiles.length > 0)));

  const start = async () => {
    setBusy(true);
    setError("");
    const result = await api.post<Live>("/api/absorb/start", {
      mode, prompt, links: mode === "given" ? linkList : [], uploads: mode === "given" ? readyFiles.map((f) => f.id) : [], settings,
    }, 120_000);
    setBusy(false);
    if (result.ok) onStarted(result.data);
    else setError(result.error);
  };

  const slider = (key: keyof Settings, label: string, format: (value: number) => string, step = 1) => {
    const [low, high] = limit(key);
    const value = Number(settings[key]);
    return (
      <label className="ab-slider">
        <span>{label}</span>
        <output>{format(value)}</output>
        <input type="range" min={low} max={high} step={step} value={value}
          onChange={(e) => setSettings((s) => ({ ...s, [key]: Number(e.target.value) }))} />
      </label>
    );
  };

  return (
    <div className="ab-card" aria-labelledby="ab-start-title">
      <div className="ab-actions" style={{ justifyContent: "space-between" }}>
        <h2 id="ab-start-title" className="ab-label" style={{ margin: 0 }}>New study run</h2>
        <span className="ab-note">One run at a time · it keeps facts, never the downloaded files</span>
      </div>
      <div className="ab-modes" role="radiogroup" aria-label="How Nyx studies">
        {MODES.map((item) => (
          <button key={item.id} type="button" role="radio" aria-checked={mode === item.id} className="ab-mode" onClick={() => setMode(item.id)}>
            <b>{item.title}</b>
            <span>{item.body}</span>
          </button>
        ))}
      </div>

      {mode === "prompt" && (
        <label className="ab-field">
          <span>What should Nyx learn?</span>
          <textarea className="ab-textarea" value={prompt} onChange={(e) => setPrompt(e.target.value)} autoFocus
            placeholder="e.g. options pricing and the Greeks, then how traders hedge them" />
        </label>
      )}

      {mode === "given" && (
        <div className="ab-grid-2">
          <div className="ab-field">
            <span>Files</span>
            <div className={`ab-drop${over ? " is-over" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); void addFiles(Array.from(e.dataTransfer.files)); }}>
              <span>Drop PDFs, Word, PowerPoint, spreadsheets, text or pictures here</span>
              <button type="button" className="ab-btn" onClick={() => picker.current?.click()}>Choose Files…</button>
              <input ref={picker} type="file" multiple hidden onChange={(e) => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
            </div>
            {files.length > 0 && (
              <div className="ab-files" aria-live="polite">
                {files.map((f) => (
                  <span key={f.key} className="ab-file" title={f.error || f.name}>
                    {f.name}{!f.id && !f.error ? " · uploading…" : f.error ? " · failed" : ""}
                    <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((current) => current.filter((x) => x.key !== f.key))}>×</button>
                  </span>
                ))}
              </div>
            )}
          </div>
          <label className="ab-field">
            <span>Links (one per line — papers, GitHub repositories, articles)</span>
            <textarea className="ab-textarea" value={links} onChange={(e) => setLinks(e.target.value)}
              placeholder={"https://arxiv.org/abs/2205.14135\nhttps://github.com/ollama/ollama"} />
          </label>
        </div>
      )}

      <div className="ab-grid-2">
        {mode !== "given" && (
          <div className="ab-field">
            <span>Where it reads</span>
            <div className="ab-tags" role="group" aria-label="Sources">
              {overview.sources.map((name) => (
                <button key={name} type="button" className="ab-tag" aria-pressed={settings.sources[name] !== false}
                  onClick={() => setSettings((s) => ({ ...s, sources: { ...s.sources, [name]: s.sources[name] === false } }))}>
                  <span className="ab-tag__box" aria-hidden="true" />{SOURCE_LABELS[name] ?? name}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="ab-grid-2" style={{ gap: 10 }}>
          {mode !== "given" && slider("minutes", "How long", (v) => (v ? `${v} min` : "until I stop"), 5)}
          {slider("depth", "Lines per document", (v) => `${v}`)}
          {slider("speed", "Reading speed", (v) => `${v.toFixed(2)}×`, 0.25)}
          {slider("parallel", "Documents at once", (v) => `${v}`)}
          {mode === "auto" && slider("breadth", "Topics at once", (v) => `${v}`)}
        </div>
      </div>

      {error && <p className="ab-error" role="alert">{error}</p>}
      <div className="ab-actions">
        <button className="ab-btn is-primary" style={{ minWidth: 160 }} disabled={!canStart} onClick={() => void start()}>
          {busy ? "Starting…" : mode === "auto" ? "Start Studying" : mode === "given" ? "Study These" : "Study This"}
        </button>
        <span className="ab-note">
          Facts go into Nyx's memory tagged with the run, so you can take them back out afterwards. Uses the “Data absorption” model
          in Keys & Models — set it to Ollama to study without any online model.
        </span>
      </div>
    </div>
  );
}
