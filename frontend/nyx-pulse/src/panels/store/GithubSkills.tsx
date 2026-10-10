/** Add capability → Skills from GitHub (skill_import.py): paste a link, see every SKILL.md with warnings, pick, add. */

import { useState } from "react";
import { api } from "../../api";

interface Found { path: string; url: string; name: string; description: string; size: number; warnings: string[]; too_big: boolean }

export function GithubSkills({ onAdded }: { onAdded: () => void }) {
  const [url, setUrl] = useState("");
  const [found, setFound] = useState<{ repo: string; skills: Found[] } | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  const look = async () => {
    setBusy("look"); setNote(""); setFound(null);
    const r = await api.post<{ repo: string; skills: Found[] }>("/api/skills/github/preview", { url }, 120000);
    setBusy("");
    if (!r.ok) { setNote(r.error); return; }
    setFound(r.data);
    setPicked(new Set(r.data.skills.filter((s) => !s.warnings.length && !s.too_big).map((s) => s.path)));
  };

  const add = async () => {
    setBusy("add");
    const r = await api.post<{ added: { name: string }[] }>("/api/skills/github/import", { url, paths: [...picked] }, 120000);
    setBusy("");
    if (!r.ok) { setNote(r.error); return; }
    setNote(`Added ${r.data.added.map((a) => a.name).join(", ")}.`);
    setFound(null);
    onAdded();
  };

  const toggle = (path: string) => setPicked((now) => {
    const next = new Set(now);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });

  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 6 }}>Skills from GitHub</div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginBottom: 10, lineHeight: 1.6 }}>
        Paste a repo or folder with SKILL.md files (the format Claude Code and OpenJarvis use). Only the instructions
        come in — scripts in the repo are never run.
      </div>
      <form style={{ display: "flex", gap: 8 }} onSubmit={(e) => { e.preventDefault(); void look(); }}>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/anthropics/skills"
          aria-label="GitHub link" style={{ flex: 1, padding: "8px 11px", background: "var(--color-nav)", color: "var(--color-text)",
            border: "none", borderRadius: "var(--radius)", boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 13 }} />
        <button className="btn btn-secondary" disabled={!!busy || !url.trim()}>{busy === "look" ? "Looking…" : "Find Skills"}</button>
      </form>
      {note && <div style={{ fontSize: 12.5, marginTop: 8 }} role="status">{note}</div>}
      {found && (
        <div style={{ marginTop: 10, display: "grid", gap: 6 }}>
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>{found.skills.length} in {found.repo}</div>
          {found.skills.map((s) => (
            <label key={s.path} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, lineHeight: 1.45 }}>
              <input type="checkbox" checked={picked.has(s.path)} onChange={() => toggle(s.path)} disabled={s.too_big} style={{ marginTop: 3 }} />
              <span>
                <b>{s.name}</b> <a href={s.url} target="_blank" rel="noreferrer" style={{ fontSize: 11.5 }}>view</a>
                <span style={{ display: "block", color: "var(--color-neutral-500)" }}>{s.description}</span>
                {s.warnings.length > 0 && <span style={{ display: "block", color: "var(--color-warn)" }}>⚠ {s.warnings.join("; ")} — read it before adding.</span>}
                {s.too_big && <span style={{ display: "block", color: "var(--color-warn)" }}>Too long to import (over 60 KB).</span>}
              </span>
            </label>
          ))}
          <button className="btn btn-primary" style={{ justifySelf: "start" }} disabled={!!busy || picked.size === 0} onClick={() => void add()}>
            {busy === "add" ? "Adding…" : `Add ${picked.size} Skill${picked.size === 1 ? "" : "s"}`}
          </button>
        </div>
      )}
    </div>
  );
}
