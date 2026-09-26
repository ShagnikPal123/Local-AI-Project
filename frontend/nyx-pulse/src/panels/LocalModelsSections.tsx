/** Keys & Models → Local models, and the model finder at the very bottom (Request R12–R13).
 *
 * "In keys also add a way to add local models so basically it's another part where if I have a download I click on it
 * and it adds to the overall model" — the models Ollama already has, the .gguf files sitting in Downloads, a download
 * by name, and any local server that is already running.
 *
 * "Add a model finder. It searches extremely hard to find more models for free and gives the link or search so the user
 * can find an api key for it … Last resort kind of thing." — so it sits last, and every result carries its key page.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { onWorkspaceEvent } from "../state/workspaceEvents";

interface OllamaModel { name: string; bytes: number; family: string; parameters: string; quantization: string; modified: string }
interface Suggested { name: string; gb: number; job: string; fits: "gpu" | "ram" | "no"; installed: boolean }
interface LocalStatus {
  installed: boolean; running: boolean; exe: string; host: string; models: OllamaModel[]; active: string;
  memory: { vram_gb: number; ram_gb: number }; total_bytes: number; suggested: Suggested[]; store: string;
}
interface LocalJob {
  id: string; kind: string; title: string; status: string; percent: number; detail: string; error: string;
  started_at: number; ended_at: number;
}
interface LocalServer { name: string; url: string; port: number; models: string[] }
interface ModelFile { path: string; name: string; bytes: number; gb: number; kind: string; quantization: string; fits: string; ready: boolean }
interface FinderResult {
  id: string; kind: string; provider: string; label: string; free: string; signup: string; chat_url: string;
  model: string; note: string; source: string; score: number;
}
interface FinderJob { id: string; query: string; status: string; step: string; results: FinderResult[]; error: string; searched: string[] }

const FITS_LABEL: Record<string, string> = { gpu: "fits your GPU", ram: "runs on the processor (slower)", no: "too big for this PC" };

function gb(bytes: number): string {
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

export function LocalModels() {
  const [state, setState] = useState<{ status: LocalStatus; jobs: LocalJob[]; servers: LocalServer[] } | null>(null);
  const [files, setFiles] = useState<ModelFile[] | null>(null);
  const [pullName, setPullName] = useState("");
  const [message, setMessage] = useState("");
  const [confirmRemove, setConfirmRemove] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<{ status: LocalStatus; jobs: LocalJob[]; servers: LocalServer[] }>("/api/local-models");
    if (result.ok) setState(result.data); else setMessage(result.error);
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => onWorkspaceEvent((event) => { if (event.type === "local_models.job" || event.type === "keys.changed") void load(); }), [load]);
  const working = state?.jobs.some((j) => j.status === "running");
  useEffect(() => {
    if (!working) return;
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 1500);
    return () => window.clearInterval(timer);
  }, [working, load]);

  const scan = async () => {
    setBusy("scan");
    const result = await api.post<{ files: ModelFile[] }>("/api/local-models/scan", {}, 60_000);
    setBusy("");
    if (result.ok) { setFiles(result.data.files); setMessage(result.data.files.length ? "" : "No model files found in Downloads, the Desktop, Documents or the usual model folders."); }
    else setMessage(result.error);
  };
  const post = async (path: string, body?: unknown, note = "") => {
    setBusy(path);
    const result = await api.post(path, body ?? {}, 120_000);
    setBusy("");
    setMessage(result.ok ? note : result.error);
    await load();
  };
  const remove = async (name: string) => {
    setConfirmRemove("");
    const result = await api.del(`/api/local-models/${encodeURIComponent(name)}`);
    setMessage(result.ok ? `Removed ${name} and freed its disk space.` : result.error);
    await load();
  };

  if (!state) return null;
  const { status, jobs, servers } = state;

  return (
    <section className="keys-section">
      <h2 className="keys-heading">Local models on this PC</h2>
      <p className="keys-notes">
        Models that run on your own graphics card: free, private and available offline. This PC has{" "}
        {status.memory.vram_gb ? `${status.memory.vram_gb.toFixed(1)} GB of video memory` : "no GPU Nyx can see"} and{" "}
        {status.memory.ram_gb.toFixed(0)} GB of memory.
      </p>

      {!status.installed ? (
        <div className="card keys-provider">
          <div className="keys-provider__head"><strong>Ollama is not installed</strong><span className="keys-status">needed for local models</span></div>
          <p className="keys-notes">
            Ollama runs the models. Nyx can install it for you with winget, or you can get it from ollama.com and come back.
          </p>
          <div className="keys-actions">
            <button className="btn btn-primary" disabled={Boolean(busy)} onClick={() => void post("/api/local-models/install", {}, "Installing Ollama — this takes a few minutes.")}>
              Install Ollama
            </button>
            <a className="btn btn-secondary" href="https://ollama.com/download" target="_blank" rel="noopener noreferrer">Download it myself ↗</a>
          </div>
        </div>
      ) : (
        <>
          <div className="keys-grid">
            {status.models.map((model) => (
              <div key={model.name} className="card keys-provider" data-configured={status.active === model.name}>
                <div className="keys-provider__head">
                  <strong>{model.name}</strong>
                  {status.active === model.name && <span className="keys-badge">In use offline</span>}
                  <span className="keys-status">{gb(model.bytes)}</span>
                </div>
                <p className="keys-notes">{[model.parameters, model.quantization, model.family].filter(Boolean).join(" · ") || "local model"}</p>
                <div className="keys-actions">
                  <button className="btn btn-primary" disabled={status.active === model.name}
                    onClick={() => void post("/api/local-models/use", { name: model.name }, `${model.name} is now the model Nyx uses offline.`)}>
                    Use Offline
                  </button>
                  <button className="btn btn-secondary"
                    onClick={() => void post("/api/local-models/use", { name: model.name, role: "data_absorption" }, `${model.name} now does the Data absorption job.`)}>
                    Give It Studying
                  </button>
                  {confirmRemove === model.name ? (
                    <>
                      <span className="keys-notes">Delete it from this PC?</span>
                      <button className="btn btn-secondary" onClick={() => void remove(model.name)}>Delete</button>
                      <button className="btn btn-secondary" onClick={() => setConfirmRemove("")}>Cancel</button>
                    </>
                  ) : (
                    <button className="btn btn-secondary" onClick={() => setConfirmRemove(model.name)}>Remove</button>
                  )}
                </div>
              </div>
            ))}
            {status.models.length === 0 && <p className="keys-notes">Ollama is installed but has no models yet — download one below.</p>}
          </div>

          <div className="card keys-provider">
            <strong>Download a model</strong>
            <p className="keys-notes">Sized for this PC. “Fits your GPU” means it runs fast; anything bigger still works, just slower.</p>
            <div className="keys-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
              {status.suggested.map((item) => (
                <div key={item.name} className="card" style={{ padding: 10, display: "grid", gap: 4 }}>
                  <strong style={{ fontSize: 13 }}>{item.name}</strong>
                  <span className="keys-notes">{item.job} · {item.gb} GB · {FITS_LABEL[item.fits]}</span>
                  <button className="btn btn-secondary" disabled={item.installed || item.fits === "no" || Boolean(busy)}
                    onClick={() => void post("/api/local-models/pull", { name: item.name }, `Downloading ${item.name}…`)}>
                    {item.installed ? "Already here" : "Download"}
                  </button>
                </div>
              ))}
            </div>
            <form className="keys-form" onSubmit={(e) => { e.preventDefault(); if (pullName.trim()) void post("/api/local-models/pull", { name: pullName.trim() }, `Downloading ${pullName.trim()}…`); }}>
              <label className="keys-field">
                <span>Or a model by name (anything on ollama.com)</span>
                <input value={pullName} onChange={(e) => setPullName(e.target.value)} placeholder="qwen3:14b" spellCheck={false} />
              </label>
              <div className="keys-actions"><button className="btn btn-primary" type="submit" disabled={!pullName.trim() || Boolean(busy)}>Download</button></div>
            </form>
          </div>

          <div className="card keys-provider">
            <strong>A model file you already downloaded</strong>
            <p className="keys-notes">
              Nyx looks through Downloads, the Desktop, Documents and the LM Studio, GPT4All, Jan and Hugging Face folders for
              <code> .gguf</code> files. Adding one copies it into Ollama's own store, so it uses that much disk again.
            </p>
            <div className="keys-actions">
              <button className="btn btn-secondary" disabled={busy === "scan"} onClick={() => void scan()}>{busy === "scan" ? "Looking…" : "Look For Model Files"}</button>
            </div>
            {files && files.length > 0 && (
              <div className="keys-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
                {files.map((file) => (
                  <div key={file.path} className="card" style={{ padding: 10, display: "grid", gap: 4 }}>
                    <strong style={{ fontSize: 13, overflowWrap: "anywhere" }}>{file.name}</strong>
                    <span className="keys-notes" title={file.path}>{file.gb} GB{file.quantization ? ` · ${file.quantization}` : ""} · {FITS_LABEL[file.fits]}</span>
                    <button className="btn btn-primary" disabled={!file.ready || Boolean(busy)}
                      onClick={() => void post("/api/local-models/add-file", { path: file.path }, `Adding ${file.name} to Ollama…`)}>
                      {file.ready ? "Add To Nyx" : "Needs converting first"}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {servers.length > 0 && (
        <div className="card keys-provider">
          <strong>Local servers already running</strong>
          <p className="keys-notes">These speak the same protocol as the online providers. Add one as a model below (no key needed).</p>
          {servers.map((server) => (
            <p key={server.url} className="keys-notes">
              <strong>{server.name}</strong> on port {server.port} — {server.models.slice(0, 4).join(", ") || "no models loaded"}
              {" · "}<code>{server.url}</code>
            </p>
          ))}
        </div>
      )}

      {jobs.filter((job) => job.status === "running" || Date.now() / 1000 - job.ended_at < 300).slice(0, 3).map((job) => (
        <div key={job.id} className="card keys-provider" aria-live="polite">
          <div className="keys-provider__head">
            <strong>{job.title}</strong>
            <span className="keys-status">{job.status === "running" ? `${job.percent.toFixed(0)}%` : job.status}</span>
          </div>
          <div className="dispatch__bar"><span style={{ width: `${job.percent}%` }} /></div>
          <p className={`keys-message ${job.error ? "is-error" : "is-ok"}`}>{job.error || job.detail}</p>
        </div>
      ))}
      {message && <p className="keys-message is-ok" aria-live="polite">{message}</p>}
    </section>
  );
}

export function ModelFinder() {
  const [job, setJob] = useState<FinderJob | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<{ job: FinderJob | null }>("/api/model-finder");
    if (result.ok && result.data.job) setJob(result.data.job);
  }, []);
  useEffect(() => { if (open) void load(); }, [open, load]);
  useEffect(() => {
    if (job?.status !== "running") return;
    const timer = window.setInterval(async () => {
      const result = await api.get<{ job: FinderJob }>(`/api/model-finder/${job.id}`);
      if (result.ok) setJob(result.data.job);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job?.status, job?.id]);

  const search = async () => {
    setError("");
    const result = await api.post<{ job: FinderJob }>("/api/model-finder/search", { query, deep: true }, 60_000);
    if (result.ok) setJob(result.data.job); else setError(result.error);
  };

  const use = (result: FinderResult) => {
    // Hand the details to the Add-a-model form above; the owner types the key there.
    try {
      sessionStorage.setItem("nyx.custommodel.prefill", JSON.stringify({
        name: result.label, company: result.provider, model: result.model, chat_url: result.chat_url, free: true,
      }));
    } catch { /* private window */ }
    window.dispatchEvent(new CustomEvent("nyx:prefill-model"));
  };

  return (
    <section className="keys-section">
      <h2 className="keys-heading">Find more models</h2>
      <p className="keys-notes">
        A last resort when nothing here answers: Nyx searches for providers that give models away, reads what it finds, and
        hands you the page where the key comes from. It never types a key for you.
      </p>
      <div className="keys-actions">
        <button className="btn btn-secondary" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "Hide The Finder" : "Open The Model Finder"}
        </button>
      </div>
      {open && (
        <div className="card keys-provider">
          <form className="keys-form" onSubmit={(e) => { e.preventDefault(); void search(); }}>
            <label className="keys-field">
              <span>What kind of model do you need? (optional)</span>
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="vision · code · long context · images" />
            </label>
            <div className="keys-actions">
              <button className="btn btn-primary" type="submit" disabled={job?.status === "running"}>
                {job?.status === "running" ? "Searching…" : "Search Hard"}
              </button>
              {job?.status === "running" && <span className="keys-notes" aria-live="polite">{job.step}</span>}
            </div>
          </form>
          {error && <p className="keys-message is-error">{error}</p>}
          {job && (
            <>
              {job.error && <p className="keys-message is-error">{job.error}</p>}
              <p className="keys-notes">{job.results.length} places found{job.searched.length ? ` · searched ${job.searched.length} ways` : ""}</p>
              <div className="keys-grid">
                {job.results.map((result) => (
                  <div key={result.id} className="card keys-provider">
                    <div className="keys-provider__head">
                      <strong>{result.label}</strong>
                      {result.kind === "openrouter" && <span className="keys-badge">Free model</span>}
                      {result.note && <span className="keys-status">{result.note}</span>}
                    </div>
                    <p className="keys-notes">{result.free}</p>
                    {result.model && <p className="keys-notes"><code>{result.model}</code></p>}
                    <div className="keys-actions">
                      {result.signup && (
                        <a className="btn btn-primary" href={result.signup} target="_blank" rel="noopener noreferrer">Get A Key ↗</a>
                      )}
                      {result.chat_url && <button className="btn btn-secondary" onClick={() => use(result)}>Use This Above</button>}
                      {result.source?.startsWith("http") && (
                        <a className="btn btn-secondary" href={result.source} target="_blank" rel="noopener noreferrer">Where this came from ↗</a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
