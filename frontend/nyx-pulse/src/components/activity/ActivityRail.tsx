/** What Ichos touched, live, on the right of the chat (owner, 2026-10-10: "On the right try to show more like files
 * used, code accessed, things done").
 *
 * Every tool step of every recent turn becomes a row, coloured by what it touched — files, code, web, mail,
 * messages, docs, Ichos itself — newest first, with a running count per kind at the top. A row that names something
 * openable (a file path, a mailbox, a link, a graph) opens it beside the chat on click, and can be dragged onto the
 * window pane or into the message box. Rows animate in as Ichos works, so the chat reads like watching it happen.
 */

import { useMemo, useState } from "react";
import { useStore } from "../../state/store";
import { turnsStore } from "../../state/turnStore";
import type { ToolStep } from "../chat/types";
import { DRAG_TYPE, openChatWindow, type DragOpen } from "../windows/ChatWindows";
import "./activity.css";

type Kind = "files" | "code" | "web" | "email" | "messages" | "docs" | "ichos";

const KINDS: Record<Kind, { label: string; color: string; glyph: string }> = {
  files: { label: "Files", color: "var(--pop-amber)", glyph: "▤" },
  code: { label: "Code", color: "var(--pop-mint)", glyph: "</>" },
  web: { label: "Web", color: "var(--pop-cyan)", glyph: "◍" },
  email: { label: "Mail", color: "var(--pop-coral)", glyph: "✉" },
  messages: { label: "Texts", color: "var(--pop-lime)", glyph: "✆" },
  docs: { label: "Docs", color: "var(--pop-pink)", glyph: "✎" },
  ichos: { label: "Done", color: "var(--pop-violet)", glyph: "✦" },
};

export function classify(step: Pick<ToolStep, "name" | "category">): Kind {
  const n = `${step.name} ${step.category}`.toLowerCase();
  if (/whatsapp|sms|text_|message_send|imessage/.test(n)) return "messages";
  if (/email|mail/.test(n)) return "email";
  if (/python|shell|command|code|git|claude|build|preview/.test(n)) return "code";
  if (/web|search|fetch|browse|url|news|link|research/.test(n)) return "web";
  if (/note|doc|slide|pdf|obsidian|notion/.test(n)) return "docs";
  if (/file|folder|path|read|write|drive|upload/.test(n)) return "files";
  return "ichos";
}

function target(step: ToolStep): string {
  const a = step.args ?? {};
  const pick = ["path", "file", "file_path", "folder", "url", "query", "to", "subject", "expressions", "task", "question", "name"]
    .map((k) => a[k]).find((v) => typeof v === "string" && v.trim());
  return String(pick ?? "").slice(0, 120);
}

/** What a row opens when clicked or dragged, if anything. */
export function opener(step: ToolStep, kind: Kind): DragOpen | null {
  const a = step.args ?? {};
  const path = [a.path, a.file, a.file_path].find((v) => typeof v === "string" && /[\\/]|\.\w{1,5}$/.test(v as string)) as string | undefined;
  if (path) return { kind: "file", title: path.split(/[\\/]/).pop(), props: { path } };
  if (kind === "email") return { kind: "email", title: "Mail", props: typeof a.query === "string" ? { query: a.query } : undefined };
  if (kind === "messages") return { kind: "whatsapp", title: "WhatsApp" };
  if (step.name === "plot_function" && typeof a.expressions === "string") {
    return { kind: "graph", title: "Graph", props: { expressions: (a.expressions as string).split(";").map((s) => s.trim()).filter(Boolean) } };
  }
  return null;
}

function ago(ms: number): string {
  const s = Math.max(0, (Date.now() - ms) / 1000);
  return s < 60 ? "now" : s < 3600 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`;
}

export function ActivityRail({ onClose }: { onClose: () => void }) {
  const turns = useStore(turnsStore, (s) => s.turns);
  const [filter, setFilter] = useState<Kind | "all">("all");
  const rows = useMemo(() => {
    const out: { step: ToolStep; kind: Kind; key: string }[] = [];
    for (const turn of Object.values(turns)) {
      for (const step of turn.steps ?? []) out.push({ step, kind: classify(step), key: `${turn.turnId}:${step.callId}` });
    }
    return out.sort((a, b) => b.step.startedAt - a.step.startedAt).slice(0, 120);
  }, [turns]);
  const counts = useMemo(() => {
    const c: Partial<Record<Kind, number>> = {};
    rows.forEach((r) => { c[r.kind] = (c[r.kind] ?? 0) + 1; });
    return c;
  }, [rows]);
  const shown = filter === "all" ? rows : rows.filter((r) => r.kind === filter);

  return (
    <aside className="activity" aria-label="What Ichos touched">
      <header className="activity__head">
        <h2>Activity</h2>
        <button type="button" className="shell-icon-btn" onClick={onClose} aria-label="Hide activity" title="Hide activity">⟩</button>
      </header>
      <div className="activity__filters" role="group" aria-label="Show">
        <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All <b>{rows.length}</b></button>
        {(Object.keys(KINDS) as Kind[]).filter((k) => counts[k]).map((k) => (
          <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)} style={{ ["--k" as string]: KINDS[k].color }}>
            {KINDS[k].label} <b>{counts[k]}</b>
          </button>
        ))}
      </div>
      {shown.length === 0 && (
        <p className="activity__empty">Files Ichos opens, code it runs, pages it reads and things it does show up here as it works. Drag any of them beside the chat.</p>
      )}
      <ol className="activity__list">
        {shown.map(({ step, kind, key }) => {
          const open = opener(step, kind);
          const what = target(step);
          return (
            <li key={key}>
              <button
                type="button"
                className={`activity-item is-${step.status}`}
                style={{ ["--k" as string]: KINDS[kind].color }}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData("text/plain", what || step.label);
                  if (open) e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(open));
                }}
                onClick={() => { if (open) openChatWindow(open.kind, open.title, open.props); }}
                title={open ? "Open beside the chat (or drag it)" : step.label}
              >
                <span className="activity-item__glyph" aria-hidden="true">{KINDS[kind].glyph}</span>
                <span className="activity-item__text">
                  <b>{step.label || step.name}</b>
                  {what && <small>{what}</small>}
                </span>
                <span className="activity-item__when">{step.status === "running" ? "…" : step.status === "error" ? "✗" : ago(step.startedAt)}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
