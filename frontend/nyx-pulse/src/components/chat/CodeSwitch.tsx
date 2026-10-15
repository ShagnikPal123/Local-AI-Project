/** Code inside the normal chat: a Chat / Code switch with a folder and an environment (Drive doc 2, item 2.1).
 *
 * The owner, with a picture of Claude's own switch: normal chat is where he and other users reach coding,
 * so it should not need a separate tab. In Code, a chat holds a folder and an environment, the same pair
 * Claude's Code sessions show ("Ai Dev Folder ✓", "Choose environment"), and every message carries them.
 * The server checks the folder exists and names it to the model (chat_modes.code_session); "Review first"
 * is gated there too, so the switch cannot widen anything.
 *
 * The choice is remembered per chat, like the mode slider: "this chat is the one where it codes in that
 * folder" is a property of the chat.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { pushToast } from "../../state/toastStore";

export type CodeEnvironment = "local" | "review";

export interface CodeState {
  on: boolean;
  folder: string;
  environment: CodeEnvironment;
}

interface Workspace { id: string; path: string; name: string }
interface PickResult { cancelled: boolean; opened: Workspace[]; errors: string[]; workspaces: Workspace[] }

/** Same names and words as chat_modes.CODE_ENVIRONMENTS on the server. */
export const ENVIRONMENTS: Record<CodeEnvironment, { name: string; means: string }> = {
  local: { name: "This PC", means: "Reads, edits and runs commands in the folder, with the usual approval gates." },
  review: { name: "Review first", means: "Reads the folder and shows every change as a diff to apply. Edits and runs nothing." },
};

const KEY = "nyx.chat.code";
const OFF: CodeState = { on: false, folder: "", environment: "local" };
/** The folder picker waits for the owner, so the request may take minutes (as in the Code tab). */
const PICKER_TIMEOUT_MS = 11 * 60_000;

function read(chatId: string): CodeState {
  try {
    const saved = JSON.parse(localStorage.getItem(`${KEY}.${chatId}`) || "null") as Partial<CodeState> | null;
    if (saved && typeof saved === "object") {
      return {
        on: Boolean(saved.on),
        folder: typeof saved.folder === "string" ? saved.folder : "",
        environment: saved.environment === "review" ? "review" : "local",
      };
    }
  } catch { /* private browsing or a broken entry: start in Chat */ }
  return OFF;
}

function remember(chatId: string, state: CodeState): void {
  try { localStorage.setItem(`${KEY}.${chatId}`, JSON.stringify(state)); } catch { /* not worth telling anyone */ }
}

/** The last folder a code chat used, so a new chat switched to Code starts there (like Claude's picker does). */
function lastFolder(): string {
  try { return localStorage.getItem(`${KEY}.last`) || ""; } catch { return ""; }
}

export function folderName(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

/** This chat's Code state, following the chat as it changes. `picking` is the folder card being open. */
export function useCodeSession(chatId: string) {
  const [state, setState] = useState<CodeState>(() => read(chatId));
  const [picking, setPicking] = useState(false);

  useEffect(() => { setState(read(chatId)); setPicking(false); }, [chatId]);

  const update = useCallback((patch: Partial<CodeState>) => {
    setState((current) => {
      const next = { ...current, ...patch };
      if (next.on && !next.folder) next.folder = lastFolder();
      remember(chatId, next);
      if (next.folder) { try { localStorage.setItem(`${KEY}.last`, next.folder); } catch { /* fine */ } }
      return next;
    });
  }, [chatId]);

  /** What the chat sends with each message: nothing in Chat, the folder and environment in Code. */
  const payload = state.on && state.folder ? { folder: state.folder, environment: state.environment } : undefined;
  return { state, update, picking: state.on && (picking || !state.folder), setPicking, payload };
}

/** The Chat / Code switch, two icons like Claude's at the top of the chat. */
export function ChatCodeSwitch({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <div className="code-switch" role="group" aria-label="Chat or Code">
      <button type="button" className="code-switch__option" aria-pressed={!on} title="Chat" onClick={() => onChange(false)}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12Z" /></svg><span className="sr-only">Chat</span>
      </button>
      <button type="button" className="code-switch__option" aria-pressed={on} title="Code: work in a folder" onClick={() => onChange(true)}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" /></svg><span className="sr-only">Code</span>
      </button>
    </div>
  );
}

/** The card above the composer: which folder, which environment. Shown until a folder is chosen, then on demand. */
export function CodeSessionCard({ state, onChange, onClose }: {
  state: CodeState;
  onChange: (patch: Partial<CodeState>) => void;
  onClose: () => void;
}) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [folderOpen, setFolderOpen] = useState(!state.folder);
  const [envOpen, setEnvOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    void api.get<{ workspaces: Workspace[] }>("/api/code/workspaces").then((r) => { if (alive && r.ok) setWorkspaces(r.data.workspaces); });
    return () => { alive = false; };
  }, []);

  const choose = (path: string) => {
    onChange({ folder: path });
    setFolderOpen(false);
  };

  /** File Explorer's own folder picker on this PC (the same one the Code tab opens). */
  const browse = async () => {
    setBusy(true);
    const result = await api.post<PickResult>("/api/code/pick-folders", { multiple: false, open: true }, PICKER_TIMEOUT_MS);
    setBusy(false);
    if (!result.ok) { pushToast(result.error || "Could not open the folder picker.", "error"); return; }
    setWorkspaces(result.data.workspaces);
    if (result.data.opened[0]) choose(result.data.opened[0].path);
    else if (result.data.errors[0]) pushToast(result.data.errors[0], "error");
  };

  /** A pasted path: the server checks it is a folder before it becomes one. */
  const openTyped = async () => {
    const path = typed.trim().replace(/^"|"$/g, "");
    if (!path) return;
    setBusy(true);
    const result = await api.post<{ workspace: Workspace }>("/api/code/workspaces", { path });
    setBusy(false);
    if (!result.ok) { pushToast(result.error || "That folder could not be opened.", "error"); return; }
    setWorkspaces((current) => [result.data.workspace, ...current.filter((w) => w.id !== result.data.workspace.id)]);
    setTyped("");
    choose(result.data.workspace.path);
  };

  const env = ENVIRONMENTS[state.environment];
  return (
    <div className="code-card" role="group" aria-label="Code session: folder and environment">
      <div className="code-card__row">
        <button type="button" className="code-card__pick" aria-expanded={folderOpen} onClick={() => setFolderOpen((v) => !v)}
          title={state.folder || "Choose a folder"}>
          <span aria-hidden="true">▭</span>
          <span className="code-card__label">{state.folder ? folderName(state.folder) : "Choose a folder"}</span>
          {state.folder && <span className="code-card__check" aria-label="chosen">✓</span>}
        </button>
        {state.folder && <button type="button" className="code-card__close" onClick={onClose} aria-label="Done" title="Done">
          <span aria-hidden="true">✕</span>
        </button>}
      </div>
      {folderOpen && (
        <div className="code-card__menu">
          {workspaces.map((w) => (
            <button key={w.id} type="button" className="code-card__item" aria-pressed={w.path === state.folder}
              onClick={() => choose(w.path)} title={w.path}>
              <span>{w.name || folderName(w.path)}</span>
              <small>{w.path}</small>
            </button>
          ))}
          <button type="button" className="code-card__item code-card__item--action" disabled={busy} onClick={() => void browse()}>
            <span aria-hidden="true">▤</span> {busy ? "Waiting for the folder picker…" : "Open a folder on this PC…"}
          </button>
          <form className="code-card__typed" onSubmit={(e) => { e.preventDefault(); void openTyped(); }}>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="or paste a folder path" aria-label="Folder path" />
            <button type="submit" className="btn btn-secondary" disabled={busy || !typed.trim()}>Use</button>
          </form>
        </div>
      )}
      <div className="code-card__row code-card__row--env">
        <button type="button" className="code-card__pick code-card__pick--env" aria-expanded={envOpen} onClick={() => setEnvOpen((v) => !v)}>
          <span className="code-card__label">{state.folder || state.environment !== "local" ? env.name : "Choose environment"}</span>
          <span aria-hidden="true">▾</span>
        </button>
      </div>
      {envOpen && (
        <div className="code-card__menu">
          {(Object.keys(ENVIRONMENTS) as CodeEnvironment[]).map((key) => (
            <button key={key} type="button" className="code-card__item" aria-pressed={key === state.environment}
              onClick={() => { onChange({ environment: key }); setEnvOpen(false); }}>
              <span>{ENVIRONMENTS[key].name}</span>
              <small>{ENVIRONMENTS[key].means}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Under the composer in Code: the folder and environment, like Claude's "Ai Dev Folder · Auto". Click to change.
 *  "Open in Code" opens the same folder in the Code tab (it is opened as a workspace there first). */
export function CodeBar({ state, onOpen }: { state: CodeState; onOpen: () => void }) {
  if (!state.on || !state.folder) return null;
  const openInCode = async () => {
    const result = await api.post<{ workspace: Workspace }>("/api/code/workspaces", { path: state.folder });
    if (!result.ok) { pushToast(result.error, "error"); return; }
    window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "code" } }));
  };
  return (
    <span className="code-bar-row">
      <button type="button" className="code-bar" onClick={onOpen} title={`${state.folder} · ${ENVIRONMENTS[state.environment].means}`}>
        <span aria-hidden="true">▭</span>
        <span>{folderName(state.folder)}</span>
        <span className="code-bar__env">{ENVIRONMENTS[state.environment].name}</span>
      </button>
      <button type="button" className="code-bar code-bar__link" onClick={() => void openInCode()} title="Open this folder in the Code tab">
        Open in Code
      </button>
    </span>
  );
}

interface Proposal {
  id: string;
  path: string;
  name: string;
  explanation?: string;
  instruction?: string;
  diff?: string;
  status: string;
  added?: number;
  removed?: number;
}

/** Review first, in the chat: the changes Ichos proposed for this folder, each with Apply and Skip.
 *  Nothing is written until Apply; Apply keeps a backup, so the Code tab can undo it. `refreshKey` changes after
 *  every turn so new proposals show up as soon as the answer ends. */
export function CodeProposals({ state, refreshKey }: { state: CodeState; refreshKey: unknown }) {
  const [items, setItems] = useState<Proposal[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const folder = state.on && state.environment === "review" ? state.folder : "";

  const load = useCallback(async () => {
    if (!folder) { setItems([]); return; }
    const result = await api.get<{ proposals: Proposal[] }>(`/api/code/proposals?under=${encodeURIComponent(folder)}`);
    if (result.ok) setItems(result.data.proposals.filter((p) => p.status === "proposed"));
  }, [folder]);
  useEffect(() => { void load(); }, [load, refreshKey]);

  if (!folder || items.length === 0) return null;
  const act = async (proposal: Proposal, apply: boolean) => {
    const result = apply
      ? await api.post(`/api/code/proposals/${proposal.id}/apply`, {})
      : await api.post(`/api/code/proposals/${proposal.id}/resolve`, { status: "rejected" });
    if (!result.ok) pushToast(result.error, "error");
    else pushToast(apply ? `Applied the change to ${proposal.name}.` : `Skipped the change to ${proposal.name}.`);
    void load();
  };
  return (
    <div className="code-proposals" role="region" aria-label="Changes to review">
      <div className="code-proposals__head">{items.length} change{items.length === 1 ? "" : "s"} to review</div>
      {items.map((p) => (
        <div key={p.id} className="code-proposals__item">
          <button type="button" className="code-proposals__name" onClick={() => setOpen(open === p.id ? null : p.id)} aria-expanded={open === p.id}>
            <b>{p.name}</b>
            <span className="code-proposals__count">+{p.added ?? 0} −{p.removed ?? 0}</span>
            {(p.explanation || p.instruction) && <span className="code-proposals__why">{p.explanation || p.instruction}</span>}
          </button>
          <span className="code-proposals__actions">
            <button type="button" className="btn" onClick={() => void act(p, true)}>Apply</button>
            <button type="button" className="btn btn-ghost" onClick={() => void act(p, false)}>Skip</button>
          </span>
          {open === p.id && p.diff && <pre className="code-proposals__diff">{p.diff}</pre>}
        </div>
      ))}
    </div>
  );
}
