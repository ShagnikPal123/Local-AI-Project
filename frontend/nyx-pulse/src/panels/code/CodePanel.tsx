/** The Code tab: open a folder or one huge file, tell Nyx what to change, review the diff (Request G7).
 *
 * Request H1 (the owner's main focus): "Open Folders…" opens File Explorer's own folder picker on
 * this PC — search, Quick access, Ctrl/Shift-click several folders — and every folder chosen opens.
 * Request H12: New File / New Folder in the tree, Start From Scratch (empty or starter folder), and
 * Nyx can build files into an empty folder (a proposal of new files, applied only on Accept).
 *
 * Files, the file, and Nyx — like Cursor or Claude Code, but every edit arrives
 * as a diff you accept or reject, with an undo while the file is untouched. Big
 * files open as a fast line viewer that loads in pieces; select lines by clicking
 * their numbers (Shift-click extends) to aim Nyx at just that part.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api";
import { Markdown } from "../../components/chat/Markdown";
import { DiffSummary, describeLines, parseDiff, type LineStats } from "../../components/DiffSummary";
import { Toasts } from "../../components/chat";
import { pushToast, useToasts, dismissToast } from "../../state/toastStore";
import { PreviewBar } from "./PreviewBar";
import "./code.css";

interface Workspace { id: string; path: string; name: string; file: string }
interface Entry { name: string; path: string; dir: boolean; size: number }
interface FileChunk { path: string; name: string; language: string; size: number; total_lines: number; start: number; end: number; text: string; hash: string }
interface Proposal {
  id: string; path: string; name: string; instruction: string; explanation: string; diff: string; model: string;
  status: "proposed" | "applied" | "rejected" | "stale" | "undone" | "applied_in_editor"; added: number; removed: number; created_at: number;
  kind?: "create"; files?: { relative: string; lines: number }[]; skipped?: string[];
  /** Which lines of which file (Request R9), from the server. */
  lines?: LineStats;
}
interface Starter { id: string; label: string; description: string }
interface PickResult { paths: string[]; cancelled: boolean; opened: Workspace[]; errors: string[]; workspaces: Workspace[] }

/** The folder picker waits for the owner, so the request may take minutes. */
const PICKER_TIMEOUT_MS = 11 * 60_000;

const EDITABLE_BYTES = 300_000;
const LINE_HEIGHT = 20;
const CHUNK = 2000;

function sizeLabel(bytes: number): string {
  return bytes > 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} MB` : bytes > 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes} B`;
}

function Tree({ root, onOpen, activePath, onFolder, targetDir, refresh }: {
  root: string; onOpen: (path: string) => void; activePath: string;
  onFolder: (path: string) => void; targetDir: string; refresh: number;
}) {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => {
    void api.get<{ entries: Entry[] }>(`/api/code/tree?path=${encodeURIComponent(root)}`).then((r) => setEntries(r.ok ? r.data.entries : []));
  }, [root, refresh]);
  if (!entries) return <div className="code-tree__loading">Loading…</div>;
  if (entries.length === 0) return <div className="code-tree__loading">Empty folder</div>;
  return (
    <ul className="code-tree" role="group">
      {entries.map((entry) => (
        <li key={entry.path} role="treeitem" aria-expanded={entry.dir ? Boolean(open[entry.path]) : undefined}>
          <button className={`code-tree__row${activePath === entry.path || (entry.dir && targetDir === entry.path) ? " is-active" : ""}`}
            onClick={() => {
              if (entry.dir) { setOpen((o) => ({ ...o, [entry.path]: !o[entry.path] })); onFolder(entry.path); }
              else onOpen(entry.path);
            }}
            title={entry.dir ? entry.path : `${entry.path} · ${sizeLabel(entry.size)}`}>
            <span className="code-tree__icon" aria-hidden="true">{entry.dir ? (open[entry.path] ? "▾" : "▸") : "·"}</span>
            <span className="code-tree__name">{entry.name}</span>
            {!entry.dir && entry.size > EDITABLE_BYTES && <span className="code-tree__big">{sizeLabel(entry.size)}</span>}
          </button>
          {entry.dir && open[entry.path] && <Tree root={entry.path} onOpen={onOpen} activePath={activePath} onFolder={onFolder} targetDir={targetDir} refresh={refresh} />}
        </li>
      ))}
    </ul>
  );
}

/** Start From Scratch: a new folder from a starter, somewhere the owner chooses. */
function StartSheet({ onClose, onStarted }: { onClose: () => void; onStarted: (workspace: Workspace) => void }) {
  const [starters, setStarters] = useState<Starter[]>([]);
  const [parents, setParents] = useState<string[]>([]);
  const [parent, setParent] = useState("");
  const [name, setName] = useState("");
  const [starter, setStarter] = useState("empty");
  const [busy, setBusy] = useState<"pick" | "create" | null>(null);
  const nameField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameField.current?.focus();
    void api.get<{ templates: Starter[]; parents: string[] }>("/api/code/templates").then((r) => {
      if (!r.ok) return;
      setStarters(r.data.templates);
      setParents(r.data.parents);
      setParent((p) => p || r.data.parents[0] || "");
    });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function choose() {
    setBusy("pick");
    const result = await api.post<PickResult>("/api/code/pick-folders", { multiple: false, open: false, start: parent }, PICKER_TIMEOUT_MS);
    setBusy(null);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    const picked = result.data.paths[0];
    if (picked) { setParent(picked); setParents((list) => (list.includes(picked) ? list : [picked, ...list])); }
  }

  async function create() {
    setBusy("create");
    const result = await api.post<{ workspace: Workspace }>("/api/code/start", { parent, name, template: starter });
    setBusy(null);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    onStarted(result.data.workspace);
  }

  const where = parent && name.trim() ? `${parent.replace(/[\\/]+$/, "")}\\${name.trim()}` : "";
  return (
    <div className="code-sheet__scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <form className="code-sheet" role="dialog" aria-modal="true" aria-labelledby="code-start-title"
        onSubmit={(e) => { e.preventDefault(); if (parent && name.trim() && !busy) void create(); }}>
        <h2 id="code-start-title">Start From Scratch</h2>
        <p className="code__muted">Nyx makes a new folder, adds the starter files you pick, and opens it here.</p>
        <label className="code-sheet__field">
          <span>Folder name</span>
          <input ref={nameField} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Weather App" />
        </label>
        <div className="code-sheet__field">
          <span>Location</span>
          <div className="code-sheet__row">
            <select value={parent} onChange={(e) => setParent(e.target.value)} aria-label="Location">
              {parents.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <button type="button" className="btn btn-secondary" disabled={busy !== null} onClick={() => void choose()}>
              {busy === "pick" ? "Waiting for you…" : "Choose…"}
            </button>
          </div>
        </div>
        <fieldset className="code-sheet__starters">
          <legend>Starter</legend>
          {starters.map((item) => (
            <label key={item.id} className={`code-starter${starter === item.id ? " is-picked" : ""}`}>
              <input type="radio" name="starter" value={item.id} checked={starter === item.id} onChange={() => setStarter(item.id)} />
              <b>{item.label}</b>
              <span>{item.description}</span>
            </label>
          ))}
        </fieldset>
        {where && <p className="code__muted">Creates <code>{where}</code></p>}
        <div className="code-sheet__foot">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={!parent || !name.trim() || busy !== null}>{busy === "create" ? "Creating…" : "Create Folder"}</button>
        </div>
      </form>
    </div>
  );
}

function DiffView({ diff }: { diff: string }) {
  return (
    <pre className="code-diff" aria-label="Proposed changes">
      {diff.split("\n").map((line, i) => (
        <span key={i} className={line.startsWith("+++") || line.startsWith("---") ? "is-file" : line.startsWith("@@") ? "is-hunk" : line.startsWith("+") ? "is-add" : line.startsWith("-") ? "is-del" : ""}>
          {line || " "}
        </span>
      ))}
    </pre>
  );
}

export function CodePanel() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [current, setCurrent] = useState<Workspace | null>(null);
  const [openPath, setOpenPath] = useState("");
  const [meta, setMeta] = useState<FileChunk | null>(null);
  const [chunks, setChunks] = useState<Record<number, string[]>>({});
  const [draft, setDraft] = useState<string | null>(null);
  const [selection, setSelection] = useState<[number, number] | null>(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState<"propose" | "ask" | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [answer, setAnswer] = useState<{ answer: string; model: string } | null>(null);
  const [search, setSearch] = useState("");
  const [hits, setHits] = useState<{ path: string; line: number; text: string }[] | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const viewer = useRef<HTMLDivElement>(null);
  const editor = useRef<HTMLTextAreaElement>(null);
  const toasts = useToasts();

  const loadWorkspaces = useCallback(async () => {
    const result = await api.get<{ workspaces: Workspace[] }>("/api/code/workspaces");
    if (result.ok) {
      setWorkspaces(result.data.workspaces);
      setCurrent((c) => c ?? result.data.workspaces[0] ?? null);
    } else pushToast(result.error, "warn");
  }, []);
  useEffect(() => { void loadWorkspaces(); }, [loadWorkspaces]);

  const loadProposals = useCallback(async (path: string) => {
    const result = await api.get<{ proposals: Proposal[] }>(`/api/code/proposals?path=${encodeURIComponent(path)}`);
    if (result.ok) setProposals(result.data.proposals);
  }, []);

  const openFile = useCallback(async (path: string) => {
    const result = await api.get<FileChunk>(`/api/code/file?path=${encodeURIComponent(path)}&start=1&end=${CHUNK}`);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setOpenPath(path);
    setMeta(result.data);
    setChunks({ 0: result.data.text.split("\n") });
    setDraft(result.data.size <= EDITABLE_BYTES ? null : null);
    setSelection(null);
    setAnswer(null);
    setScrollTop(0);
    if (viewer.current) viewer.current.scrollTop = 0;
    void loadProposals(path);
  }, [loadProposals]);

  useEffect(() => { if (current?.file && !openPath) void openFile(current.file); }, [current, openPath, openFile]);

  // --- H1: File Explorer's folder picker; H12: new files and folders -------------------------------
  const [picking, setPicking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [showPath, setShowPath] = useState(false);
  const [targetDir, setTargetDir] = useState("");
  const [creating, setCreating] = useState<"file" | "folder" | null>(null);
  const [newName, setNewName] = useState("");
  const [treeRefresh, setTreeRefresh] = useState(0);

  async function pickFolders() {
    setPicking(true);
    const result = await api.post<PickResult>("/api/code/pick-folders", { multiple: true, open: true }, PICKER_TIMEOUT_MS);
    setPicking(false);
    if (!result.ok) { pushToast(result.error, "warn"); setShowPath(true); return; }
    for (const error of result.data.errors) pushToast(error, "warn");
    if (result.data.cancelled) return;
    setWorkspaces(result.data.workspaces);
    const first = result.data.opened[0];
    if (first) { setCurrent(first); setTargetDir(first.path); setOpenPath(""); setMeta(null); setHits(null); }
    const count = result.data.opened.length;
    pushToast(count === 1 ? `Opened ${first?.name}.` : `Opened ${count} folders — switch between them above the files.`, "ok");
  }

  async function closeWorkspace(workspace: Workspace) {
    const result = await api.del<{ workspaces: Workspace[] }>(`/api/code/workspaces/${workspace.id}`);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setWorkspaces(result.data.workspaces);
    if (current?.id === workspace.id) { setCurrent(result.data.workspaces[0] ?? null); setMeta(null); setOpenPath(""); }
  }

  async function createEntry() {
    const base = targetDir || current?.path;
    if (!base || !newName.trim() || !creating) return;
    const path = `${base.replace(/[\\/]+$/, "")}\\${newName.trim()}`;
    const result = await api.post<{ file?: { path: string }; folder?: { path: string } }>(
      creating === "file" ? "/api/code/new-file" : "/api/code/new-folder", { path });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setCreating(null);
    setNewName("");
    setTreeRefresh((n) => n + 1);
    if (result.data.file) void openFile(result.data.file.path);
    else if (result.data.folder) setTargetDir(result.data.folder.path);
  }

  const [pathInput, setPathInput] = useState("");
  async function openWorkspace() {
    const result = await api.post<{ workspace: Workspace }>("/api/code/workspaces", { path: pathInput });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setPathInput("");
    setCurrent(result.data.workspace);
    setOpenPath("");
    setMeta(null);
    await loadWorkspaces();
    if (result.data.workspace.file) void openFile(result.data.workspace.file);
  }

  const editable = Boolean(meta && meta.size <= EDITABLE_BYTES);
  const fullText = editable && meta ? (draft ?? meta.text) : "";
  const dirty = editable && draft !== null && meta !== null && draft !== meta.text;

  // Big files: fetch the chunk under the viewport on demand.
  useEffect(() => {
    if (!meta || editable) return;
    const first = Math.floor(scrollTop / LINE_HEIGHT);
    const index = Math.floor(first / CHUNK);
    for (const i of [index, index + 1]) {
      if (i * CHUNK >= meta.total_lines || chunks[i]) continue;
      setChunks((c) => ({ ...c, [i]: [] }));
      void api.get<FileChunk>(`/api/code/file?path=${encodeURIComponent(meta.path)}&start=${i * CHUNK + 1}&end=${(i + 1) * CHUNK}`)
        .then((r) => { if (r.ok) setChunks((c) => ({ ...c, [i]: r.data.text.split("\n") })); });
    }
  }, [scrollTop, meta, editable, chunks]);

  function lineAt(n: number): string | undefined {
    const chunk = chunks[Math.floor((n - 1) / CHUNK)];
    return chunk ? chunk[(n - 1) % CHUNK] : undefined;
  }

  function pickLine(n: number, extend: boolean) {
    setSelection((sel) => (extend && sel ? [Math.min(sel[0], n), Math.max(sel[1], n)] : [n, n]));
  }

  function editorSelection() {
    const el = editor.current;
    if (!el || el.selectionStart === el.selectionEnd) return;
    const before = el.value.slice(0, el.selectionStart).split("\n").length;
    const through = el.value.slice(0, el.selectionEnd).split("\n").length;
    setSelection([before, through]);
  }

  async function save() {
    if (!meta || draft === null) return;
    const result = await api.put<{ hash: string }>("/api/code/file", { path: meta.path, text: draft, base_hash: meta.hash });
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setMeta({ ...meta, text: draft, hash: result.data.hash });
    setDraft(null);
    pushToast("Saved. The previous version is backed up.", "ok");
  }

  async function buildFiles() {
    if (!current || !instruction.trim()) return;
    setBusy("propose");
    const result = await api.post<{ proposal: Proposal }>("/api/code/propose-files", { root: targetDir || current.path, instruction }, 180_000);
    setBusy(null);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setProposals((p) => [result.data.proposal, ...p.filter((x) => x.id !== result.data.proposal.id)]);
    setInstruction("");
  }

  async function propose() {
    if (!meta) { void buildFiles(); return; }
    if (!instruction.trim()) return;
    if (dirty) { pushToast("Save your edits first, so Nyx changes the current version.", "warn"); return; }
    setBusy("propose");
    const result = await api.post<{ proposal: Proposal }>("/api/code/propose", {
      path: meta.path, instruction, start_line: selection?.[0], end_line: selection?.[1],
    }, 120_000);
    setBusy(null);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setProposals((p) => [result.data.proposal, ...p.filter((x) => x.id !== result.data.proposal.id)]);
    setInstruction("");
  }

  async function ask() {
    if (!meta) return;
    setBusy("ask");
    const result = await api.post<{ answer: string; model: string }>("/api/code/ask", {
      path: meta.path, question: instruction || "Explain what this code does and anything risky in it.", start_line: selection?.[0], end_line: selection?.[1],
    }, 120_000);
    setBusy(null);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setAnswer(result.data);
  }

  async function act(proposal: Proposal, action: "apply" | "undo" | "reject") {
    const result = action === "reject"
      ? await api.post<{ proposal: Proposal }>(`/api/code/proposals/${proposal.id}/resolve`, { status: "rejected" })
      : await api.post<{ proposal: Proposal }>(`/api/code/proposals/${proposal.id}/${action}`);
    if (!result.ok) { pushToast(result.error, "warn"); void loadProposals(proposal.path); return; }
    setProposals((p) => p.map((x) => (x.id === proposal.id ? result.data.proposal : x)));
    if (proposal.kind === "create") setTreeRefresh((n) => n + 1);
    else if (action !== "reject") void openFile(proposal.path);
    const touched = describeLines(proposal.lines ?? parseDiff(proposal.diff));
    pushToast(action === "apply" ? `Applied — ${touched}. A backup was kept.` : action === "undo" ? `Undone — ${touched}.` : "Change rejected.", "ok");
  }

  function useInChat() {
    if (!meta) return;
    const where = selection ? ` (lines ${selection[0]}–${selection[1]})` : "";
    try { sessionStorage.setItem("nyx.chat.prefill", `In ${meta.path}${where}: ${instruction || ""}`); } catch { /* ignore */ }
    window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "nyx" } }));
  }

  async function runSearch() {
    if (!current || !search.trim()) { setHits(null); return; }
    const result = await api.post<{ hits: { path: string; line: number; text: string }[] }>("/api/code/search", { root: current.path, query: search });
    setHits(result.ok ? result.data.hits : []);
  }

  const viewportLines = useMemo(() => {
    if (!meta || editable) return [];
    const height = viewer.current?.clientHeight ?? 800;
    const first = Math.max(1, Math.floor(scrollTop / LINE_HEIGHT) - 20);
    const last = Math.min(meta.total_lines, first + Math.ceil(height / LINE_HEIGHT) + 40);
    return Array.from({ length: Math.max(0, last - first + 1) }, (_, i) => first + i);
  }, [meta, editable, scrollTop]);

  const lineCount = editable ? fullText.split("\n").length : meta?.total_lines ?? 0;

  return (
    <div className="code">
      <aside className="code__side" aria-label="Files">
        <div className="code__launch">
          <button className="code-open-btn" onClick={() => void pickFolders()} disabled={picking} aria-describedby="code-open-hint">
            <span className="code-open-btn__icon" aria-hidden="true">
              <svg viewBox="0 0 20 20" width="18" height="18"><path d="M2.5 5.5a2 2 0 0 1 2-2h3.3l1.8 1.8h5.9a2 2 0 0 1 2 2v7.2a2 2 0 0 1-2 2H4.5a2 2 0 0 1-2-2z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" /></svg>
            </span>
            <span className="code-open-btn__text">
              <b>{picking ? "Waiting for File Explorer…" : "Open Folders…"}</b>
              <span id="code-open-hint">{picking ? "Pick folders in the window that opened, then Open in Nyx." : "Search your PC and pick one or more folders"}</span>
            </span>
          </button>
          <div className="code__launch-row">
            <button className="btn btn-secondary" onClick={() => setStarting(true)}>Start From Scratch…</button>
            <button className="chat-inline" onClick={() => setShowPath((v) => !v)} aria-expanded={showPath}>{showPath ? "Hide path" : "Type a path"}</button>
          </div>
          {showPath && (
            <form className="code__open" onSubmit={(e) => { e.preventDefault(); void openWorkspace(); }}>
              <input value={pathInput} onChange={(e) => setPathInput(e.target.value)} placeholder="C:\Users\you\project, or a file" aria-label="Folder or file path" autoFocus />
              <button className="btn btn-primary" disabled={!pathInput.trim()}>Open</button>
            </form>
          )}
        </div>
        {workspaces.length > 0 && (
          <div className="code-roots" role="list" aria-label="Opened folders">
            {workspaces.map((w) => (
              <div key={w.id} role="listitem" className={`code-root${current?.id === w.id ? " is-current" : ""}`}>
                <button className="code-root__name" title={w.path} aria-current={current?.id === w.id ? "true" : undefined}
                  onClick={() => { setCurrent(w); setTargetDir(w.path); setHits(null); }}>
                  <b>{w.name}</b><span>{w.path}</span>
                </button>
                <button className="code-root__close" aria-label={`Close ${w.name} (files stay on disk)`} title="Close (files stay on disk)" onClick={() => void closeWorkspace(w)}>×</button>
              </div>
            ))}
          </div>
        )}
        {current && (
          <>
            <form className="code__search" onSubmit={(e) => { e.preventDefault(); void runSearch(); }}>
              <input type="search" value={search} onChange={(e) => { setSearch(e.target.value); if (!e.target.value) setHits(null); }} placeholder={`Search in ${current.name}`} aria-label="Search in folder" />
            </form>
            <div className="code-newbar">
              <span className="code__muted" title={targetDir || current.path}>In {(targetDir || current.path).split(/[\\/]/).pop()}</span>
              <button className="chat-inline" onClick={() => { setCreating("file"); setNewName(""); }}>New File</button>
              <button className="chat-inline" onClick={() => { setCreating("folder"); setNewName(""); }}>New Folder</button>
            </div>
            <PreviewBar folder={targetDir || current.path} />
            {creating && (
              <form className="code__open" onSubmit={(e) => { e.preventDefault(); void createEntry(); }}>
                <input value={newName} onChange={(e) => setNewName(e.target.value)} autoFocus aria-label={creating === "file" ? "New file name" : "New folder name"}
                  placeholder={creating === "file" ? "name.ext (or folder/name.ext)" : "Folder name"}
                  onKeyDown={(e) => { if (e.key === "Escape") setCreating(null); }} />
                <button className="btn btn-primary" disabled={!newName.trim()}>Create</button>
              </form>
            )}
            {hits ? (
              <ul className="code-hits">
                {hits.length === 0 && <li className="code__muted">No matches.</li>}
                {hits.map((h, i) => (
                  <li key={i}><button onClick={() => { void openFile(h.path).then(() => setSelection([h.line, h.line])); }}>
                    <b>{h.path.split(/[\\/]/).pop()}:{h.line}</b><span>{h.text}</span>
                  </button></li>
                ))}
              </ul>
            ) : (
              <Tree key={current.path} root={current.path} onOpen={(p) => void openFile(p)} activePath={openPath}
                onFolder={setTargetDir} targetDir={targetDir} refresh={treeRefresh} />
            )}
          </>
        )}
        {!current && <p className="code__muted">Open one or more project folders, or start a new one. Nyx reads and edits only folders you open.</p>}
      </aside>

      <section className="code__main" aria-label="File">
        {!meta ? (
          <div className="code__blank">
            {current ? (
              <>
                <h2>Pick a file — or build one</h2>
                <p>Open a file from the list, make a New File, or tell Nyx what to build in {current.name}. New files arrive as a proposal you accept first.</p>
              </>
            ) : (
              <>
                <h2>Open a folder to start</h2>
                <p>Open Folders… shows File Explorer so you can search and pick one or several. Start From Scratch makes a new folder.</p>
                <div className="code__blank-actions">
                  <button className="btn btn-primary" onClick={() => void pickFolders()} disabled={picking}>Open Folders…</button>
                  <button className="btn btn-secondary" onClick={() => setStarting(true)}>Start From Scratch…</button>
                </div>
              </>
            )}
          </div>
        ) : (
          <>
            <header className="code__filebar">
              <b title={meta.path}>{meta.name}</b>
              <span className="code__muted">{meta.language} · {lineCount.toLocaleString()} lines · {sizeLabel(meta.size)}{editable ? "" : " · read-only view (large file)"}</span>
              {selection && <button className="chip" onClick={() => setSelection(null)} title="Clear selection">Lines {selection[0]}–{selection[1]} ✕</button>}
              {dirty && <button className="btn btn-primary" onClick={() => void save()}>Save</button>}
              {dirty && <button className="btn btn-secondary" onClick={() => setDraft(null)}>Revert</button>}
            </header>
            {editable ? (
              <div className="code__editor">
                <div className="code__gutter" aria-hidden="true" style={{ transform: `translateY(${-scrollTop}px)` }}>
                  {Array.from({ length: lineCount }, (_, i) => (
                    <div key={i} className={selection && i + 1 >= selection[0] && i + 1 <= selection[1] ? "is-selected" : ""}>{i + 1}</div>
                  ))}
                </div>
                <textarea ref={editor} className="code__textarea" spellCheck={false} value={fullText} wrap="off" aria-label={`Edit ${meta.name}`}
                  onChange={(e) => setDraft(e.target.value)} onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
                  onMouseUp={editorSelection} onKeyUp={(e) => { if (e.shiftKey) editorSelection(); }}
                  onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); void save(); } }} />
              </div>
            ) : (
              <div ref={viewer} className="code__viewer" onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)} tabIndex={0} aria-label={`${meta.name}, read-only`}>
                <div style={{ height: meta.total_lines * LINE_HEIGHT, position: "relative" }}>
                  {viewportLines.map((n) => {
                    const text = lineAt(n);
                    const picked = selection && n >= selection[0] && n <= selection[1];
                    return (
                      <div key={n} className={`code__line${picked ? " is-selected" : ""}`} style={{ top: (n - 1) * LINE_HEIGHT }}>
                        <button className="code__num" onClick={(e) => pickLine(n, e.shiftKey)} aria-label={`Select line ${n}`}>{n}</button>
                        <span className="code__text">{text === undefined ? "…" : text || " "}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </section>

      <aside className="code__nyx" aria-label="Nyx">
        <h2>Nyx</h2>
        <p className="code__muted">{meta ? (selection ? `Working on lines ${selection[0]}–${selection[1]} of ${meta.name}.` : `Working on the whole of ${meta.name}.`) : current ? `Building in ${(targetDir || current.path).split(/[\\/]/).pop()} — new files only.` : "Open a folder to start."}</p>
        <textarea className="code__ask" rows={4} value={instruction} onChange={(e) => setInstruction(e.target.value)} disabled={!meta && !current}
          placeholder={meta ? "Tell Nyx what to change — e.g. “add error handling to load_config” — or ask a question." : "Describe what to build — e.g. “a to-do list web page with local storage”."}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); void propose(); } }} />
        <div className="code__actions">
          <button className="btn btn-primary" disabled={(!meta && !current) || !instruction.trim() || Boolean(busy)} onClick={() => void propose()}>
            {busy === "propose" ? (meta ? "Writing the change…" : "Writing files…") : meta ? "Propose Edit" : "Build Files"}
          </button>
          {meta && <button className="btn btn-secondary" disabled={!instruction.trim() || Boolean(busy)} onClick={() => void buildFiles()} title="Create new files next to this one instead of editing it">New Files</button>}
          {meta && <button className="btn btn-secondary" disabled={Boolean(busy)} onClick={() => void ask()}>{busy === "ask" ? "Reading…" : instruction.trim() ? "Ask" : "Explain"}</button>}
          {meta && <button className="btn btn-secondary" onClick={useInChat} title="Continue in the Nyx chat with this file named">Use in Chat</button>}
        </div>
        {busy === "propose" && (
          <p className="code__working" role="status">
            {meta
              ? `Writing a change to ${meta.name}${selection ? `, lines ${selection[0]}–${selection[1]}` : ""}…`
              : `Writing new files in ${(targetDir || current?.path || "").split(/[\\/]/).pop()}…`}
          </p>
        )}

        {answer && (
          <div className="code-card">
            <div className="code-card__head"><b>Answer</b><span className="code__muted">{answer.model}</span><button className="chat-inline" onClick={() => setAnswer(null)}>Dismiss</button></div>
            <div className="code-card__body"><Markdown text={answer.answer} /></div>
          </div>
        )}

        {proposals.map((p) => (
          <div key={p.id} className={`code-card is-${p.status}`}>
            <div className="code-card__head">
              <b>{p.instruction}</b>
              <span className="code__muted">{p.model}</span>
            </div>
            <DiffSummary lines={p.lines} diff={p.diff} verb={p.kind === "create" ? "Creates" : "Changes"} />
            {p.explanation && <p className="code-card__explain">{p.explanation}</p>}
            {p.kind === "create" && p.files && (
              <ul className="code-card__files" aria-label="New files">
                {p.files.map((f) => <li key={f.relative}><code>{f.relative}</code><span className="code__muted">{f.lines} lines</span></li>)}
                {(p.skipped ?? []).map((name) => <li key={`skip-${name}`} className="code__muted">Skipped {name}</li>)}
              </ul>
            )}
            {p.status === "proposed" && <DiffView diff={p.diff} />}
            <div className="code-card__foot">
              {p.status === "proposed" && (
                <>
                  <button className="btn btn-secondary" onClick={() => void act(p, "reject")}>Reject</button>
                  <button className="btn btn-primary" onClick={() => void act(p, "apply")}>{p.kind === "create" ? "Create Files" : "Accept"}</button>
                </>
              )}
              {p.status === "applied" && <><span className="code__muted">Applied</span><button className="btn btn-secondary" onClick={() => void act(p, "undo")}>Undo</button></>}
              {p.status !== "proposed" && p.status !== "applied" && <span className="code__muted">{p.status === "stale" ? "File changed — ask again" : p.status.replace(/_/g, " ")}</span>}
            </div>
          </div>
        ))}
      </aside>
      {starting && (
        <StartSheet onClose={() => setStarting(false)} onStarted={(workspace) => {
          setStarting(false);
          setCurrent(workspace); setTargetDir(workspace.path); setOpenPath(""); setMeta(null); setHits(null);
          void loadWorkspaces();
          pushToast(`Created and opened ${workspace.name}. Tell Nyx what to build.`, "ok");
        }} />
      )}
      <Toasts items={toasts} onDismiss={dismissToast} />
    </div>
  );
}
