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

interface LineupModel { id: string; name: string; size_label: string; tagline: string }
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
                    title={`${m.size_label}: ${m.tagline}`}>{m.name}</button>
                ))}
              </div>
            </section>
          ))}
          {catalog && (
            <section className="lp-fam">
              <header>Effort <span>How hard it works</span></header>
              <EffortSlider efforts={catalog.efforts} value={effort} onPick={(id) => void setEffort(id)} />
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

/** The glowing effort slider (Fixer Upper WS5: "the rainbow effort slider"): one stop per effort from Low to Aleph on
 * a cool-to-hot track, the part up to the thumb lit and the thumb glowing in its own colour. "Auto" sits beside it and
 * lets Ichos pick per message. Arrow keys move one stop; the name and what it means show under the track. */
const HUES = ["#38bdf8", "#34d399", "#a3e635", "#facc15", "#fb923c", "#f43f5e", "#c084fc", "#e879f9"];

export function EffortSlider({ efforts, value, onPick }: { efforts: Effort[]; value: string; onPick: (id: string) => void }) {
  const auto = value === "auto" || !efforts.some((e) => e.id === value);
  const at = auto ? -1 : efforts.findIndex((e) => e.id === value);
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? at;
  const last = Math.max(1, efforts.length - 1);
  const colour = (i: number) => HUES[Math.round((i / last) * (HUES.length - 1))] ?? HUES[0];
  const pct = at < 0 ? 0 : (at / last) * 100;
  const stops = efforts.map((_, i) => `${colour(i)} ${(i / last) * 100}%`).join(", ");
  return (
    <div className={`lp-effort-slider${auto ? " is-auto" : ""}`}
      style={{ ["--fx-stops" as string]: stops, ["--fx-pct" as string]: `${pct}%`, ["--fx-glow" as string]: at < 0 ? "transparent" : colour(at) }}>
      <div className="lp-effort-slider__row">
        <button type="button" className={`lp-chip${auto ? " is-on" : ""}`} title="Picked per message" onClick={() => onPick("auto")}>Auto</button>
        <div className="lp-effort-slider__track">
          <input type="range" min={0} max={efforts.length - 1} step={1} value={at < 0 ? 0 : at}
            aria-label="Effort" aria-valuetext={at < 0 ? "Auto" : efforts[at]?.name}
            onChange={(e) => onPick(efforts[Number(e.target.value)].id)}
            onPointerMove={(e) => {
              const box = e.currentTarget.getBoundingClientRect();
              setHover(Math.round(Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)) * last));
            }}
            onPointerLeave={() => setHover(null)} />
          <div className="lp-effort-slider__ticks" aria-hidden>
            {efforts.map((e, i) => <i key={e.id} className={i <= at ? "is-lit" : ""} style={{ left: `${(i / last) * 100}%` }} />)}
          </div>
        </div>
      </div>
      <div className="lp-effort-slider__label" aria-live="polite">
        {shown < 0 ? <><b>Auto</b> Picked per message</> : <><b style={{ color: colour(shown) }}>{efforts[shown]?.name}</b> {efforts[shown]?.summary}</>}
      </div>
    </div>
  );
}
