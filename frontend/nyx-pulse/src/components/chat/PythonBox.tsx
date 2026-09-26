/** Python boxes in chat (Request H10): read, edit, copy, save as a .py file, or ask Nyx about it.
 *
 * Deliberately no Run button: AGENTS.md §7 — "Execute LLM-generated code" is on the never-do
 * list, and model-written Python is exactly that. Running it is the owner's own step, in their own
 * terminal or the Code tab, where they can read it first.
 */

import { useState } from "react";
import { copyToClipboard } from "./hooks";

export function PythonBox({ code, open }: { code: string; open: boolean }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(code);
  const [copied, setCopied] = useState(false);
  const current = editing ? text : code;
  const lines = current.split("\n").length;

  function save() {
    const blob = new Blob([current.endsWith("\n") ? current : `${current}\n`], { type: "text/x-python" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    const guess = current.match(/^def\s+([a-zA-Z_]\w*)/m)?.[1] ?? "nyx_script";
    link.download = `${guess}.py`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 2000);
  }

  function ask(prompt: string) {
    window.dispatchEvent(new CustomEvent("nyx:compose", { detail: { text: `${prompt}\n\n\`\`\`python\n${current}\n\`\`\`` } }));
  }

  return (
    <figure className="py-box" data-open={open || undefined}>
      <figcaption className="py-box__bar">
        <span className="py-box__lang">Python</span>
        <span className="py-box__meta">{lines} {lines === 1 ? "line" : "lines"}{editing && text !== code ? " · edited" : ""}</span>
        {open ? <span className="nyx-md__code-live">Writing…</span> : (
          <span className="py-box__actions">
            <button type="button" className="chat-inline" aria-pressed={editing} onClick={() => { setEditing((v) => !v); if (!editing) setText(code); }}>
              {editing ? "Done Editing" : "Edit"}
            </button>
            <button type="button" className="chat-inline" onClick={async () => { setCopied(await copyToClipboard(current)); window.setTimeout(() => setCopied(false), 1600); }}>
              {copied ? "Copied" : "Copy"}
            </button>
            <button type="button" className="chat-inline" onClick={save}>Save .py</button>
            <button type="button" className="chat-inline" onClick={() => ask("Explain this Python code step by step, and say what it would print or do:")}>Explain</button>
            <button type="button" className="chat-inline" onClick={() => ask("Check this Python code for bugs and fix them:")}>Check for Bugs</button>
          </span>
        )}
      </figcaption>
      {editing ? (
        <textarea className="py-box__editor" value={text} spellCheck={false} rows={Math.min(24, Math.max(4, lines + 1))}
          aria-label="Edit Python code" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Tab") {
              e.preventDefault();
              const el = e.currentTarget;
              const start = el.selectionStart;
              const next = `${text.slice(0, start)}    ${text.slice(el.selectionEnd)}`;
              setText(next);
              window.requestAnimationFrame(() => el.setSelectionRange(start + 4, start + 4));
            }
          }} />
      ) : (
        <pre className="nyx-md__pre py-box__pre" tabIndex={0} aria-label="Python code"><code>{code}</code></pre>
      )}
      {!open && <p className="py-box__note">Nyx doesn’t run model-written code. Save it and run it yourself: <code>python {"<file>"}.py</code></p>}
    </figure>
  );
}
