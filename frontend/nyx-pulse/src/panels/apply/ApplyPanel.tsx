/** Apply (Request R16): tell Nyx what to change about itself — with files, pictures and links — and watch it plan.
 *
 * "a way to prompt the ai and also upload field, pictures m, and such so that the ai then follows it and applies to
 * itself … changing its code, adding tabs, and more. Similar to vibe coding … It can use images to understand ui
 * format. It uses apple and normal design skills together. Can search."
 *
 * The plan arrives as one box per change. Nothing happens to Nyx until the owner presses Apply on a box: a tab is
 * added as data, a Python change goes through the sandbox + tests + reviewer pipeline, an interface edit is shown as
 * a real diff first and needs a rebuild. The server (apply_engine.py) enforces all of it; this page shows it.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, uploadFile } from "../../api";
import { DiffSummary, type LineStats } from "../../components/DiffSummary";
import { Icon, type IconName } from "../../components/chat/Icon";
import "./apply.css";

type Kind = "tab" | "code" | "ui" | "skill" | "agent" | "agent_feature";

interface Change {
  index: number; kind: Kind; title: string; why: string; status: string; message?: string; error?: string;
  target?: string; path?: string; description?: string;
  preview?: { label: string; icon: string; description: string; blocks: { type: string; title: string }[]; accent: string };
  spec?: Record<string, unknown>;
  proposal?: { id: string; diff: string; lines?: LineStats; explanation?: string; model?: string } | null;
  result?: { tab_id?: string; label?: string; lines?: LineStats };
  implement?: { status?: string; state?: string; message?: string; lines?: LineStats; diff?: string };
  change_id?: string;
}
interface Step { text: string; state: "running" | "done" | "failed" | "skipped"; at: number }
interface Build { state: "idle" | "running" | "done" | "failed"; output?: string; started?: number; finished?: number }
interface Job {
  id: string; prompt: string; status: string; created: number; steps: Step[]; notes: string[]; error?: string;
  inputs: { files: { name: string; chars: number }[]; pictures: { name: string; notes: string }[]; links: { title: string; url: string }[] };
  guidance: { apple: string[]; skills: string[]; web: boolean; general?: boolean };
  understood: string; summary: string; changes: Change[]; questions: string[]; models: Record<string, string>;
  needs_rebuild: boolean; build: Build;
}
interface Overview { jobs: { id: string; prompt: string; status: string; created: number; changes: number; applied: number }[]; build: Build; running: boolean }
interface Attachment { id: string; name: string; kind: string; preview?: string }

const KIND_LABEL: Record<Kind, string> = {
  tab: "New Tab", code: "Code Change", ui: "Interface Edit", skill: "Skill", agent: "New Agent", agent_feature: "Agent Upgrade",
};
const KIND_ICON: Record<Kind, IconName> = {
  tab: "plus", code: "code", ui: "pencil", skill: "bolt", agent: "users", agent_feature: "sparkle",
};
const WORKING = new Set(["reading", "planning", "writing"]);
const EXAMPLES = [
  "Add a tab for tracking my study hours, with a timer and a weekly chart",
  "Make the Notes tab look like this screenshot",
  "When I ask about money, always show totals first and a short table",
  "Add an agent that reviews my spreadsheets for mistakes",
];

function openTab(tab: string) {
  window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab } }));
}

export function ApplyPanel() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  const loadOverview = useCallback(async () => {
    const result = await api.get<Overview>("/api/apply");
    if (result.ok) setOverview(result.data); else setError(result.error);
  }, []);
  const loadJob = useCallback(async (id: string) => {
    const result = await api.get<Job>(`/api/apply/${id}`);
    if (result.ok) setJob(result.data); else setError(result.error);
  }, []);
  useEffect(() => { void loadOverview(); }, [loadOverview]);
  useEffect(() => {
    // Open the newest request on arrival, so a plan that finished while away is right there.
    if (!job && overview?.jobs.length) void loadJob(overview.jobs[0].id);
  }, [overview, job, loadJob]);

  // Follow a request while it is being planned, and a code change while it is being tested, or a rebuild.
  const live = Boolean(job && (WORKING.has(job.status) || job.build?.state === "running"
    || job.changes.some((c) => c.kind === "code" && c.status === "applied" && c.implement?.state === "running")));
  useEffect(() => {
    if (!job || !live) return;
    const timer = window.setInterval(() => { if (!document.hidden) void loadJob(job.id); }, 1200);
    return () => window.clearInterval(timer);
  }, [job?.id, live, loadJob]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (job && !WORKING.has(job.status)) void loadOverview(); }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="ap">
      <header className="ap-head">
        <div>
          <h1>Apply</h1>
          <p>Tell Nyx what to change about itself. Add files, pictures or links. It plans each change and applies
            one only when you press Apply.</p>
        </div>
      </header>
      {error && <p className="ap-error" role="alert">{error}</p>}
      <div className="ap-body">
        <aside className="ap-side">
          <Composer busy={Boolean(overview?.running)} onStarted={(started) => { setJob(started); void loadOverview(); }} />
          {overview && overview.jobs.length > 0 && (
            <section className="ap-card" aria-labelledby="ap-history">
              <h2 id="ap-history">Earlier Requests</h2>
              <ul className="ap-history">
                {overview.jobs.map((entry) => (
                  <li key={entry.id}>
                    <button className={entry.id === job?.id ? "is-on" : ""} onClick={() => void loadJob(entry.id)}>
                      <span className="ap-history__prompt">{entry.prompt}</span>
                      <small>{statusWord(entry.status)} · {entry.applied}/{entry.changes} applied</small>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
        <main className="ap-main">
          {job ? <JobView job={job} onJob={setJob} /> : (
            <div className="ap-empty">
              <Icon name="wand" size={34} />
              <h2>Nothing Planned Yet</h2>
              <p>Describe a change on the left. A picture of a layout you like helps Nyx match it.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function statusWord(status: string): string {
  return ({ reading: "Reading", planning: "Planning", writing: "Writing", ready: "Ready", empty: "Nothing to change",
            failed: "Failed", cancelled: "Stopped" } as Record<string, string>)[status] ?? status;
}

// ---------------------------------------------------------------------------------------------------------------------
// The request box
// ---------------------------------------------------------------------------------------------------------------------

function Composer({ busy, onStarted }: { busy: boolean; onStarted: (job: Job) => void }) {
  const [prompt, setPrompt] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [links, setLinks] = useState<string[]>([]);
  const [link, setLink] = useState("");
  const [search, setSearch] = useState(true);
  const [uploading, setUploading] = useState(0);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const add = async (files: FileList | File[]) => {
    const list = Array.from(files).slice(0, 6 - attachments.length);
    setUploading((n) => n + list.length);
    for (const file of list) {
      const result = await uploadFile(file);
      setUploading((n) => n - 1);
      if (!result.ok) { setError(result.error); continue; }
      const preview = file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
      setAttachments((current) => [...current, { id: result.data.id, name: result.data.name, kind: result.data.kind, preview }]);
    }
  };
  const remove = (id: string) => setAttachments((current) => {
    const gone = current.find((a) => a.id === id);
    if (gone?.preview) URL.revokeObjectURL(gone.preview);
    return current.filter((a) => a.id !== id);
  });
  const addLink = () => {
    const clean = link.trim();
    if (!/^https?:\/\/\S+$/i.test(clean)) { setError("Links start with http:// or https://."); return; }
    setLinks((current) => (current.includes(clean) ? current : [...current, clean].slice(0, 4)));
    setLink("");
    setError("");
  };
  const send = async () => {
    if (!prompt.trim() || sending || busy || uploading) return;
    setSending(true);
    setError("");
    const result = await api.post<Job>("/api/apply", { prompt, uploads: attachments.map((a) => a.id), links, search }, 60_000);
    setSending(false);
    if (!result.ok) { setError(result.error); return; }
    onStarted(result.data);
    setPrompt("");
    attachments.forEach((a) => a.preview && URL.revokeObjectURL(a.preview));
    setAttachments([]);
    setLinks([]);
  };

  return (
    <section className={`ap-card ap-compose${dragging ? " is-dragging" : ""}`} aria-labelledby="ap-ask"
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); if (e.dataTransfer.files.length) void add(e.dataTransfer.files); }}>
      <h2 id="ap-ask">What Should Nyx Change?</h2>
      <label className="sr-only" htmlFor="ap-prompt">Describe the change</label>
      <textarea id="ap-prompt" rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)}
        placeholder="Add a tab… make this look like the picture… teach yourself to…"
        onPaste={(e) => { const files = Array.from(e.clipboardData.files); if (files.length) { e.preventDefault(); void add(files); } }}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void send(); } }} />
      {!prompt && (
        <div className="ap-examples">
          {EXAMPLES.map((text) => <button key={text} className="ap-chip" onClick={() => setPrompt(text)}>{text}</button>)}
        </div>
      )}
      {(attachments.length > 0 || uploading > 0) && (
        <ul className="ap-attachments">
          {attachments.map((item) => (
            <li key={item.id}>
              {item.preview ? <img src={item.preview} alt="" /> : <Icon name="file" size={18} />}
              <span>{item.name}</span>
              <button className="ap-x" onClick={() => remove(item.id)} aria-label={`Remove ${item.name}`}>×</button>
            </li>
          ))}
          {uploading > 0 && <li className="is-loading"><span>Uploading {uploading}…</span></li>}
        </ul>
      )}
      <div className="ap-row">
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => { if (e.target.files) void add(e.target.files); e.target.value = ""; }} />
        <button className="ap-btn" onClick={() => fileInput.current?.click()} disabled={attachments.length >= 6}>
          <Icon name="paperclip" size={15} /> Attach
        </button>
        <label className="ap-switch">
          <input type="checkbox" role="switch" checked={search} onChange={(e) => setSearch(e.target.checked)} />
          <span>Search the web</span>
        </label>
      </div>
      <div className="ap-link">
        <label className="sr-only" htmlFor="ap-link">Add a link</label>
        <input id="ap-link" value={link} onChange={(e) => setLink(e.target.value)} placeholder="Add a link (optional)"
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addLink(); } }} />
        <button className="ap-btn" onClick={addLink} disabled={!link.trim()}>Add</button>
      </div>
      {links.length > 0 && (
        <ul className="ap-links">
          {links.map((url) => (
            <li key={url}><span>{url}</span><button className="ap-x" onClick={() => setLinks((l) => l.filter((u) => u !== url))} aria-label={`Remove ${url}`}>×</button></li>
          ))}
        </ul>
      )}
      {error && <p className="ap-error" role="alert">{error}</p>}
      <button className="ap-btn ap-btn--primary ap-send" onClick={() => void send()}
        disabled={!prompt.trim() || sending || busy || uploading > 0}>
        {sending ? "Sending…" : busy ? "Nyx Is Planning…" : "Plan the Change"}
      </button>
      <p className="ap-hint">Ctrl+Enter plans it. Drop or paste pictures here. Nothing changes until you press Apply on a step.</p>
    </section>
  );
}

// ---------------------------------------------------------------------------------------------------------------------
// One request: live steps, the plan, and a box per change
// ---------------------------------------------------------------------------------------------------------------------

function JobView({ job, onJob }: { job: Job; onJob: (job: Job) => void }) {
  const [error, setError] = useState("");
  const working = WORKING.has(job.status);

  const decide = async (index: number, action: "apply" | "skip" | "undo" | "retry") => {
    setError("");
    const result = await api.post<Job>(`/api/apply/${job.id}/changes/${index}/${action}`, {}, 240_000);
    if (result.ok) onJob(result.data); else setError(result.error);
  };
  const cancel = async () => {
    const result = await api.post<Job>(`/api/apply/${job.id}/cancel`);
    if (result.ok) onJob(result.data); else setError(result.error);
  };
  const rebuild = async () => {
    setError("");
    const result = await api.post<Build>("/api/apply/rebuild");
    if (result.ok) onJob({ ...job, build: result.data }); else setError(result.error);
  };

  return (
    <article className="ap-job" aria-live="polite">
      <header className="ap-job__head">
        <blockquote>{job.prompt}</blockquote>
        <div className="ap-row">
          <span className={`ap-pill is-${job.status}`}>{statusWord(job.status)}</span>
          {working && <button className="ap-btn" onClick={() => void cancel()}>Stop</button>}
        </div>
      </header>

      <ol className="ap-steps">
        {job.steps.map((step, index) => (
          <li key={index} className={`is-${step.state}`}>
            <span className="ap-steps__mark" aria-hidden="true" />
            {step.text}
          </li>
        ))}
      </ol>

      {(job.inputs.pictures.length > 0 || job.inputs.files.length > 0 || job.inputs.links.length > 0
        || job.guidance.apple.length > 0 || job.guidance.web) && (
        <div className="ap-used">
          {job.inputs.pictures.map((p) => (
            <details key={p.name} className="ap-used__item">
              <summary><Icon name="image" size={13} /> {p.name}</summary>
              <p>{p.notes}</p>
            </details>
          ))}
          {job.inputs.files.map((f) => <span key={f.name} className="ap-tag"><Icon name="file" size={18} /> {f.name}</span>)}
          {job.inputs.links.map((l) => <span key={l.url} className="ap-tag"><Icon name="link" size={13} /> {l.title}</span>)}
          {job.guidance.apple.length > 0 && <span className="ap-tag"><Icon name="bookmark" size={13} /> Apple HIG: {job.guidance.apple.join(", ")}</span>}
          {job.guidance.general && <span className="ap-tag">General design principles</span>}
          {job.guidance.skills.map((s) => <span key={s} className="ap-tag">Skill: {s}</span>)}
          {job.guidance.web && <span className="ap-tag"><Icon name="globe" size={13} /> Web search</span>}
        </div>
      )}

      {job.status === "failed" && <p className="ap-error" role="alert">{job.error}</p>}
      {(job.understood || job.summary) && (
        <section className="ap-plan">
          {job.understood && <p><b>What I understood.</b> {job.understood}</p>}
          {job.summary && <p><b>The plan.</b> {job.summary}</p>}
          {job.models.plan && <small>Planned by {job.models.plan}{job.models.pictures ? ` · pictures read by ${job.models.pictures}` : ""}</small>}
        </section>
      )}
      {job.questions.length > 0 && (
        <div className="ap-questions">
          <b>Nyx is not sure about:</b>
          <ul>{job.questions.map((q) => <li key={q}>{q}</li>)}</ul>
        </div>
      )}

      {job.needs_rebuild && (
        <div className="ap-rebuild" role="status">
          <div>
            <b>Interface edits are written.</b> Rebuild the app to see them — about a minute.
            {job.build?.state === "failed" && <pre className="ap-rebuild__out">{job.build.output}</pre>}
          </div>
          <button className="ap-btn ap-btn--primary" onClick={() => void rebuild()} disabled={job.build?.state === "running"}>
            {job.build?.state === "running" ? "Rebuilding…" : "Rebuild the App"}
          </button>
        </div>
      )}
      {!job.needs_rebuild && job.build?.state === "done" && (
        <div className="ap-rebuild is-done" role="status">
          <span>The app was rebuilt.</span>
          <button className="ap-btn" onClick={() => window.location.reload()}>Reload to See It</button>
        </div>
      )}

      {error && <p className="ap-error" role="alert">{error}</p>}
      <div className="ap-changes">
        {job.changes.map((change) => <ChangeBox key={change.index} change={change} onDecide={decide} />)}
      </div>
      {job.status === "empty" && <p className="ap-muted">Nyx found nothing it should change for this. Try saying more about what you want.</p>}
      {job.notes.length > 0 && (
        <details className="ap-notes">
          <summary>Left out or not read ({job.notes.length})</summary>
          <ul>{job.notes.map((note, index) => <li key={index}>{note}</li>)}</ul>
        </details>
      )}
    </article>
  );
}

function ChangeBox({ change, onDecide }: { change: Change; onDecide: (index: number, action: "apply" | "skip" | "undo" | "retry") => Promise<void> }) {
  const [open, setOpen] = useState(change.kind === "ui" || change.kind === "tab");
  const [busy, setBusy] = useState("");
  const act = async (action: "apply" | "skip" | "undo" | "retry") => {
    setBusy(action);
    await onDecide(change.index, action);
    setBusy("");
  };
  const proposed = change.status === "proposed";
  const canUndo = change.status === "applied" && (change.kind === "tab" || change.kind === "ui");
  const implement = change.implement;
  const spec = (change.spec ?? {}) as Record<string, unknown>;

  return (
    <section className={`ap-change is-${change.status}`} aria-labelledby={`ap-change-${change.index}`}>
      <header className="ap-change__head">
        <Icon name={KIND_ICON[change.kind]} size={22} />
        <div className="ap-change__titles">
          <span className="ap-change__kind">{KIND_LABEL[change.kind]}{change.target ? ` · ${change.target}` : ""}</span>
          <h3 id={`ap-change-${change.index}`}>{change.title}</h3>
          {change.why && <p>{change.why}</p>}
        </div>
        <button className="ap-disclose" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "Hide Details" : "Details"}
        </button>
      </header>

      {open && (
        <div className="ap-change__body">
          {change.kind === "tab" && change.preview && (
            <div className="ap-tabpreview">
              <div className="ap-tabpreview__bar">
                <b>{change.preview.label}</b>
                {change.preview.accent && <span className="ap-swatch" style={{ background: change.preview.accent }} aria-label={`Accent ${change.preview.accent}`} />}
              </div>
              {change.preview.description && <p>{change.preview.description}</p>}
              <ul>{change.preview.blocks.map((b, i) => <li key={i}><span className="ap-tag">{b.type}</span> {b.title}</li>)}</ul>
            </div>
          )}
          {(change.kind === "code" || change.kind === "ui") && change.description && <p className="ap-desc">{change.description}</p>}
          {change.kind === "ui" && change.proposal && (
            <>
              {change.proposal.explanation && <p className="ap-muted">{change.proposal.explanation}</p>}
              <DiffSummary lines={change.result?.lines ?? change.proposal.lines ?? null} diff={change.proposal.diff} verb="Edit" />
              <DiffView diff={change.proposal.diff} />
            </>
          )}
          {change.kind === "code" && implement && (
            <div className="ap-implement">
              <span className={`ap-pill is-${implement.state ?? "running"}`}>{implement.state ?? implement.status}</span>
              <span>{implement.message}</span>
              {implement.lines && <DiffSummary lines={implement.lines} diff={implement.diff} verb="Edit" compact />}
            </div>
          )}
          {change.kind === "skill" && (
            <div className="ap-spec">
              <p><b>{String(spec.name ?? "")}</b> — {String(spec.description ?? "")}</p>
              {Array.isArray(spec.triggers) && spec.triggers.length > 0 && <p className="ap-muted">Used when you mention: {(spec.triggers as string[]).join(", ")}</p>}
              <pre>{String(spec.instructions ?? "")}</pre>
            </div>
          )}
          {change.kind === "agent" && (
            <div className="ap-spec">
              <p><b>{String(spec.emoji ?? "")} {String(spec.name ?? "")}</b> — {String(spec.goal ?? "")}</p>
              {spec.expertise ? <p className="ap-muted">Good at: {String(spec.expertise)}</p> : null}
              {spec.instructions ? <pre>{String(spec.instructions)}</pre> : null}
            </div>
          )}
          {change.kind === "agent_feature" && (
            <div className="ap-spec">
              <p><b>{String(spec.agent ?? "")}</b> gets more to work with.</p>
              {spec.add_expertise ? <p className="ap-muted">Adds expertise: {String(spec.add_expertise)}</p> : null}
              {spec.add_instructions ? <pre>{String(spec.add_instructions)}</pre> : null}
            </div>
          )}
          {change.kind === "code" && proposed && (
            <p className="ap-muted">When you apply this, Nyx writes the edit in a sandbox, runs the tests and has the real diff
              reviewed. It lands only if all of that passes, and Improve can roll it back.</p>
          )}
        </div>
      )}

      {change.error && <p className="ap-error">{change.error}</p>}
      {change.message && <p className="ap-done">{change.message}</p>}
      <footer className="ap-row">
        {proposed && (
          <button className="ap-btn ap-btn--primary" onClick={() => void act("apply")}
            disabled={Boolean(busy) || (change.kind === "ui" && !change.proposal)}>
            {busy === "apply" ? "Applying…" : "Apply"}
          </button>
        )}
        {proposed && change.kind === "ui" && (
          <button className="ap-btn" onClick={() => void act("retry")} disabled={Boolean(busy)}>{busy === "retry" ? "Writing…" : "Write It Again"}</button>
        )}
        {proposed && <button className="ap-btn ap-btn--plain" onClick={() => void act("skip")} disabled={Boolean(busy)}>Skip</button>}
        {change.status === "applied" && change.kind === "tab" && change.result?.label && (
          <button className="ap-btn" onClick={() => openTab(change.result!.label!)}>Open the Tab</button>
        )}
        {change.status === "applied" && change.kind === "code" && <button className="ap-btn" onClick={() => openTab("improve")}>Open Improve</button>}
        {canUndo && <button className="ap-btn ap-btn--plain" onClick={() => void act("undo")} disabled={Boolean(busy)}>Undo</button>}
        {!proposed && <span className={`ap-pill is-${change.status}`}>{change.status === "applied" ? "Applied" : change.status === "skipped" ? "Skipped" : change.status === "undone" ? "Undone" : change.status}</span>}
      </footer>
    </section>
  );
}

function DiffView({ diff }: { diff: string }) {
  const [open, setOpen] = useState(false);
  if (!diff) return null;
  const lines = diff.split("\n");
  return (
    <div className="ap-diff">
      <button className="ap-disclose" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide the Code" : `Show the Code (${lines.length} lines)`}
      </button>
      {open && (
        <pre>
          {lines.map((line, index) => (
            <span key={index} className={line.startsWith("+") && !line.startsWith("+++") ? "is-add"
              : line.startsWith("-") && !line.startsWith("---") ? "is-del" : line.startsWith("@@") ? "is-hunk" : ""}>{line}{"\n"}</span>
          ))}
        </pre>
      )}
    </div>
  );
}
