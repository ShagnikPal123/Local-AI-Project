/** Equalize › Notch looks: pick how the notch looks, import a look someone shared, export one to share
 * (Fixer Upper S30: "the user can import how different notches look and when it activates").
 *
 * A look is a small JSON file of colours, corner sizes, width, a font from a list and when it opens. The engine
 * checks every value before keeping it (notch_looks.clean), so a file from anywhere can only change those things. */

import { useEffect, useRef, useState } from "react";
import { looksApi, type NotchLook } from "../../notch/notchApi";

export function NotchLooksCard() {
  const [looks, setLooks] = useState<NotchLook[]>([]);
  const [active, setActive] = useState("");
  const [paste, setPaste] = useState("");
  const [note, setNote] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const take = (r: Awaited<ReturnType<typeof looksApi.list>>) => {
    if (!r.ok) { setNote(r.error); return; }
    setLooks(r.data.looks);
    setActive(r.data.active.id);
  };
  useEffect(() => { void looksApi.list().then(take); }, []);

  const importText = async (text: string) => {
    let parsed: unknown;
    try { parsed = JSON.parse(text); } catch { setNote("That isn't a look file (not JSON)."); return; }
    const r = await looksApi.importLook(parsed);
    take(r);
    if (r.ok) { setPaste(""); setNote(`Using “${r.data.active.name}”.`); }
  };
  const exportLook = async (look: NotchLook) => {
    const r = await looksApi.exportLook(look.id);
    if (!r.ok) { setNote(r.error); return; }
    const url = URL.createObjectURL(new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${look.name.replace(/[^\w-]+/g, "-").toLowerCase() || "look"}.notch-look.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="eq-card wide">
      <h2>Notch looks<span>Colours, corners, width, font, and when it opens</span></h2>
      <div className="eq-chips">
        {looks.map((look) => (
          <span key={look.id} className="eq-chip" style={active === look.id ? { outline: "2px solid var(--color-accent)" } : undefined}>
            <button className="eq-btn small" onClick={() => void looksApi.use(look.id).then(take)} aria-pressed={active === look.id}
              style={{ background: look.colors.island, color: look.colors.ink, boxShadow: `inset 0 -3px 0 ${look.colors.accent}` }}>
              {look.name}
            </button>
            <button className="eq-btn small" onClick={() => void exportLook(look)} title="Download this look to share it">Export</button>
            {!look.built_in && <button className="eq-btn small" aria-label={`Delete ${look.name}`}
              onClick={() => void looksApi.remove(look.id).then(take)}>×</button>}
          </span>
        ))}
      </div>
      <div className="eq-row">
        <textarea className="eq-area" rows={3} value={paste} placeholder='Paste a look, e.g. {"name": "Mine", "colors": {"island": "#101820", "accent": "#FF7A45"}}'
          onChange={(e) => setPaste(e.target.value)} />
      </div>
      <div className="eq-row">
        <button className="eq-btn" disabled={!paste.trim()} onClick={() => void importText(paste)}>Import pasted look</button>
        <button className="eq-btn" onClick={() => fileRef.current?.click()}>Import a file…</button>
        <input ref={fileRef} type="file" accept=".json,application/json" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void f.text().then(importText); e.target.value = ""; }} />
        {note ? <span className="eq-muted" role="status">{note}</span> : null}
      </div>
    </section>
  );
}
