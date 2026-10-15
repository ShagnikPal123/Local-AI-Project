/** Model and effort under the chat box, like Claude's "Opus 5.5 · Medium" (Drive doc 2, image 02-a; owner 2026-10-15:
 *  "make sure the new models and model names are made and added").
 *
 *  One button shows who answers and how hard it works. It opens a list of Nyx's own lineup (model_lineup.py): Pico,
 *  Monolith (the elements Argon to Xenon, the owner's choice), Crescendo and Zencode, each with its Auto, then the
 *  effort stops from Low to Aleph. The providers (Gemini, Claude, Ollama…) stay at the bottom under "Providers", so
 *  picking one by hand works exactly as before. Picking a lineup name sends that id through the chat's provider value;
 *  the server turns it into a plan for each turn. */

import { useEffect, useRef, useState } from "react";
import { api } from "../../../api";
import { AUTO_PROVIDER, useProviders } from "../../ProviderPicker";

interface LineupModel { id: string; name: string; size_label: string; tagline: string; runs_on?: string }
interface Family { id: string; name: string; used_for: string; models: LineupModel[] }
interface Effort { id: string; name: string; summary: string }
interface Catalog { levels: Family[]; specialists: Family[]; efforts: Effort[]; effort: string; pick: string }

export function lineupLabel(catalog: Catalog | null, value: string): string {
  if (!value) return "Auto";
  for (const fam of [...(catalog?.levels ?? []), ...(catalog?.specialists ?? [])]) {
    if (fam.id === value) return `${fam.name} Auto`;
    const model = fam.models.find((m) => m.id === value);
    if (model) return `${fam.name} ${model.name}`;
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function LineupPicker({ value, onChange }: { value: string; onChange: (next: string) => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [open, setOpen] = useState(false);
  const { snapshot } = useProviders();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    void api.get<Catalog>("/api/models/lineup").then((r) => { if (alive && r.ok) setCatalog(r.data); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [open]);

  const effort = catalog?.effort ?? "auto";
  const effortName = effort === "auto" ? "Auto effort" : catalog?.efforts.find((e) => e.id === effort)?.name ?? effort;
  const pick = (next: string) => { setOpen(false); onChange(next); };
  const setEffort = async (id: string) => {
    const r = await api.put<Catalog>("/api/models/lineup", { effort: id });
    if (r.ok) setCatalog(r.data);
  };

  return (
    <div ref={ref} className="lp">
      <button type="button" className="lp-btn" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        title="Who answers, and how hard it works">
        <span className="lp-model">{lineupLabel(catalog, value)}</span>
        <span className="lp-effort">{effortName}</span>
        <span aria-hidden="true" className="lp-caret">⌄</span>
      </button>
      {open && (
        <div className="lp-pop" role="dialog" aria-label="Model and effort">
          <button type="button" className={`lp-row${value === AUTO_PROVIDER ? " is-on" : ""}`} onClick={() => pick(AUTO_PROVIDER)}>
            <b>Auto</b><span>The router picks per message</span>
          </button>
          {[...(catalog?.levels ?? []), ...(catalog?.specialists ?? [])].map((fam) => (
            <section key={fam.id} className="lp-fam">
              <header>{fam.name} <span>{fam.used_for}</span></header>
              <div className="lp-models">
                <button type="button" className={`lp-chip${value === fam.id ? " is-on" : ""}`} onClick={() => pick(fam.id)}
                  title={`${fam.name} picks the size for each message`}>Auto</button>
                {fam.models.map((m) => (
                  <button key={m.id} type="button" className={`lp-chip${value === m.id ? " is-on" : ""}`} onClick={() => pick(m.id)}
                    title={`${m.size_label}: ${m.tagline}${m.runs_on ? `. Runs on ${m.runs_on}` : ""}`}>{m.name}</button>
                ))}
              </div>
              {fam.models.filter((m) => m.id === value && m.runs_on).map((m) => (
                <div key={m.id} className="lp-runs">{m.name} runs on {m.runs_on}</div>
              ))}
            </section>
          ))}
          {catalog && (
            <section className="lp-fam">
              <header>Effort <span>How hard it works</span></header>
              <div className="lp-models lp-efforts">
                {[{ id: "auto", name: "Auto", summary: "Picked per message" }, ...catalog.efforts].map((e) => (
                  <button key={e.id} type="button" className={`lp-chip${effort === e.id ? " is-on" : ""}`} title={e.summary}
                    onClick={() => void setEffort(e.id)}>{e.name}</button>
                ))}
              </div>
            </section>
          )}
          {(snapshot?.providers.length ?? 0) > 0 && (
            <section className="lp-fam">
              <header>Providers <span>Pick one by hand</span></header>
              <div className="lp-models">
                {snapshot?.providers.map((p) => (
                  <button key={p.name} type="button" className={`lp-chip${value === p.name ? " is-on" : ""}${p.configured ? "" : " is-off"}`}
                    title={p.configured ? p.name : p.name === "ollama" ? "Not running" : "No key yet"} onClick={() => pick(p.name)}>{p.name}</button>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
