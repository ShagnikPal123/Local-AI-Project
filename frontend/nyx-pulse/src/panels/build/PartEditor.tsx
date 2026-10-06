/** Part mode: the feature tree and every tool that shapes a part.
 *
 * Each row in the tree is one shape. Selecting a row lights that shape in the
 * 3D view (a cut shows as the red volume it removes), which is how someone new
 * to CAD learns what each step of a part actually does.
 */

import { useState } from "react";
import type { Feature, FeatureOp, FeatureType, Part, Pin, PinKind, Vec3 } from "./types";
import { PIN_COLORS } from "./types";

const uid = (prefix: string) => `${prefix}${Math.random().toString(36).slice(2, 10)}`;

export const SHAPES: { type: FeatureType; label: string; hint: string }[] = [
  { type: "box", label: "Box", hint: "Plates, blocks, walls" },
  { type: "cylinder", label: "Cylinder", hint: "Posts, bosses, holes. Set sides for a hex" },
  { type: "pipe", label: "Tube", hint: "A cylinder with a wall" },
  { type: "sphere", label: "Sphere", hint: "Knobs, domes" },
  { type: "cone", label: "Cone", hint: "Tapers, countersinks" },
  { type: "wedge", label: "Wedge", hint: "Ramps, gussets, braces" },
  { type: "torus", label: "Ring", hint: "O-rings, handles" },
  { type: "extrude", label: "Outline", hint: "Draw a flat outline and push it up" },
  { type: "revolve", label: "Lathe", hint: "Spin a profile around the up axis" },
];

const SIZE_FIELDS: Record<FeatureType, { key: string; label: string }[]> = {
  box: [{ key: "w", label: "Width X" }, { key: "d", label: "Depth Z" }, { key: "h", label: "Height Y" }],
  wedge: [{ key: "w", label: "Width X" }, { key: "d", label: "Depth Z" }, { key: "h", label: "Height Y" }],
  cylinder: [{ key: "r", label: "Radius" }, { key: "h", label: "Height" }],
  pipe: [{ key: "r", label: "Outer radius" }, { key: "t", label: "Wall" }, { key: "h", label: "Height" }],
  sphere: [{ key: "r", label: "Radius" }],
  cone: [{ key: "r", label: "Bottom radius" }, { key: "r2", label: "Top radius" }, { key: "h", label: "Height" }],
  torus: [{ key: "r", label: "Ring radius" }, { key: "t", label: "Tube radius" }],
  extrude: [{ key: "h", label: "Height" }],
  revolve: [],
};

export const PROFILE_PRESETS: Record<string, { label: string; points: [number, number][]; for: "extrude" | "revolve" }> = {
  hexagon: { label: "Hexagon", for: "extrude", points: Array.from({ length: 6 }, (_, i) => [Math.round(Math.cos((i * Math.PI) / 3) * 200) / 10, Math.round(Math.sin((i * Math.PI) / 3) * 200) / 10] as [number, number]) },
  lbracket: { label: "L bracket", for: "extrude", points: [[-20, -20], [20, -20], [20, -14], [-14, -14], [-14, 20], [-20, 20]] },
  slot: { label: "Rounded slot", for: "extrude", points: [...Array.from({ length: 7 }, (_, i) => { const a = -Math.PI / 2 + (i / 6) * Math.PI; return [15 + Math.cos(a) * 6, Math.sin(a) * 6] as [number, number]; }), ...Array.from({ length: 7 }, (_, i) => { const a = Math.PI / 2 + (i / 6) * Math.PI; return [-15 + Math.cos(a) * 6, Math.sin(a) * 6] as [number, number]; })].map(([x, z]) => [Math.round(x * 10) / 10, Math.round(z * 10) / 10] as [number, number]) },
  star: { label: "Star", for: "extrude", points: Array.from({ length: 10 }, (_, i) => { const r = i % 2 ? 9 : 20; const a = (i * Math.PI) / 5 - Math.PI / 2; return [Math.round(Math.cos(a) * r * 10) / 10, Math.round(Math.sin(a) * r * 10) / 10] as [number, number]; }) },
  knob: { label: "Knob", for: "revolve", points: [[0, 0], [14, 0], [15, 2], [15, 10], [12, 14], [6, 16], [0, 16]] },
  vase: { label: "Vase", for: "revolve", points: [[0, 0], [20, 0], [26, 20], [18, 45], [14, 60], [18, 70], [16, 71], [12, 60], [15, 45], [23, 20], [18, 2], [0, 2]] },
  bushing: { label: "Flanged bushing", for: "revolve", points: [[4, 0], [14, 0], [14, 3], [8, 3], [8, 18], [4, 18]] },
};

export function newFeature(type: FeatureType, index: number): Feature {
  const size: Record<string, number> = {
    box: { w: 40, d: 30, h: 10 }, wedge: { w: 30, d: 30, h: 20 }, cylinder: { r: 10, h: 20 }, pipe: { r: 12, t: 2, h: 30 },
    sphere: { r: 12 }, cone: { r: 12, r2: 0, h: 24 }, torus: { r: 18, t: 4 }, extrude: { h: 8 }, revolve: { angle: 360 },
  }[type];
  const half = (size.h ?? size.r ?? 10) / 2;
  const feature: Feature = {
    id: uid("f"), type, name: `${SHAPES.find((s) => s.type === type)?.label ?? type} ${index + 1}`, op: "add",
    at: [0, type === "revolve" ? 0 : half, 0], rot: [0, 0, 0], size, round: 0, blend: 0, note: "",
  };
  if (type === "extrude") feature.profile = PROFILE_PRESETS.lbracket.points;
  if (type === "revolve") feature.profile = PROFILE_PRESETS.knob.points;
  return feature;
}

export function newPart(type: FeatureType): Part {
  return {
    id: "", name: "New part", kind: "mechanical", color: "#8e9bb4", material: "PETG", summary: "",
    features: [newFeature(type, 0)], pins: [], specs: {}, tags: [], source: "owner", catalog_id: "",
  };
}

function Num({ label, value, onChange, step = 1, min, title }: { label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; title?: string }) {
  const [text, setText] = useState<string | null>(null);
  return (
    <label className="bs-num" title={title}>
      <span>{label}</span>
      <input
        type="number"
        inputMode="decimal"
        step={step}
        min={min}
        value={text ?? String(Math.round(value * 100) / 100)}
        onChange={(e) => {
          setText(e.target.value);
          const parsed = Number(e.target.value);
          if (e.target.value !== "" && Number.isFinite(parsed)) onChange(min !== undefined ? Math.max(min, parsed) : parsed);
        }}
        onBlur={() => setText(null)}
      />
    </label>
  );
}

function Vec({ label, value, onChange, step = 1 }: { label: string; value: Vec3; onChange: (v: Vec3) => void; step?: number }) {
  return (
    <div className="bs-vec">
      <div className="bs-vec__label">{label}</div>
      {(["X", "Y", "Z"] as const).map((axis, i) => (
        <Num key={axis} label={axis} step={step} value={value[i]} onChange={(v) => {
          const next = [...value] as Vec3;
          next[i] = v;
          onChange(next);
        }} />
      ))}
    </div>
  );
}

const OP_LABEL: Record<FeatureOp, string> = { add: "Add", cut: "Cut away", intersect: "Keep overlap" };
const OP_ICON: Record<FeatureOp, string> = { add: "＋", cut: "−", intersect: "∩" };

export interface PartEditorProps {
  part: Part;
  activeFeatureId: string | null;
  busy: boolean;
  isNew: boolean;
  aiNote: string;
  onChange: (part: Part) => void;
  onActivate: (featureId: string | null) => void;
  onSave: (place: boolean) => void;
  onCancel: () => void;
  onSaveToLibrary: () => void;
  onAskNyx: (words: string) => void;
  onUndoAi: (() => void) | null;
}

export function PartEditor({ part, activeFeatureId, busy, isNew, aiNote, onChange, onActivate, onSave, onCancel, onSaveToLibrary, onAskNyx, onUndoAi }: PartEditorProps) {
  const [ask, setAsk] = useState("");
  const [profileText, setProfileText] = useState<{ id: string; text: string } | null>(null);
  const active = part.features.find((f) => f.id === activeFeatureId) ?? null;
  const activeIndex = active ? part.features.indexOf(active) : -1;

  const setFeature = (id: string, patch: Partial<Feature>) =>
    onChange({ ...part, features: part.features.map((f) => (f.id === id ? { ...f, ...patch } : f)) });
  const move = (index: number, delta: number) => {
    const next = [...part.features];
    const [item] = next.splice(index, 1);
    next.splice(Math.max(0, Math.min(next.length, index + delta)), 0, item);
    onChange({ ...part, features: next });
  };
  const addShape = (type: FeatureType) => {
    const feature = newFeature(type, part.features.length);
    onChange({ ...part, features: [...part.features, feature] });
    onActivate(feature.id);
  };
  const setPin = (id: string, patch: Partial<Pin>) => onChange({ ...part, pins: part.pins.map((p) => (p.id === id ? { ...p, ...patch } : p)) });

  return (
    <div className="bs-editor">
      <section className="bs-section">
        <div className="bs-section__head">
          <h3>{isNew ? "New part" : "Edit part"}</h3>
          <span className="bs-muted">{part.features.length} shape{part.features.length === 1 ? "" : "s"}</span>
        </div>
        <label className="bs-field"><span>Name</span><input value={part.name} onChange={(e) => onChange({ ...part, name: e.target.value })} /></label>
        <div className="bs-row">
          <label className="bs-field"><span>Kind</span>
            <select value={part.kind} onChange={(e) => onChange({ ...part, kind: e.target.value })}>
              {["mechanical", "enclosure", "electronic", "fastener", "material"].map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </label>
          <label className="bs-field"><span>Material</span><input value={part.material} placeholder="PLA, PETG, aluminium…" onChange={(e) => onChange({ ...part, material: e.target.value })} /></label>
          <label className="bs-field bs-field--color"><span>Colour</span><input type="color" value={part.color} onChange={(e) => onChange({ ...part, color: e.target.value })} /></label>
        </div>
      </section>

      <section className="bs-section">
        <div className="bs-section__head"><h3>Ask Nyx to change it</h3></div>
        <form className="bs-ask" onSubmit={(e) => { e.preventDefault(); if (ask.trim()) onAskNyx(ask.trim()); }}>
          <input value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="e.g. add four M3 holes 5 mm from the corners" disabled={busy} />
          <button className="btn btn-primary btn-sm" disabled={busy || !ask.trim()}>{busy ? "Working…" : "Change"}</button>
        </form>
        {aiNote && <p className="bs-note">{aiNote} {onUndoAi && <button className="bs-link" onClick={onUndoAi}>Undo</button>}</p>}
      </section>

      <section className="bs-section">
        <div className="bs-section__head"><h3>Shapes</h3><span className="bs-muted">Top to bottom, each one builds on the last</span></div>
        <ol className="bs-tree" aria-label="Shapes in this part">
          {part.features.map((feature, index) => (
            <li key={feature.id} className={`bs-tree__row${feature.id === activeFeatureId ? " is-active" : ""} is-${feature.op}`}>
              <button className="bs-tree__main" onClick={() => onActivate(feature.id === activeFeatureId ? null : feature.id)} aria-pressed={feature.id === activeFeatureId}
                title={feature.note || `${OP_LABEL[feature.op]} a ${feature.type}`}>
                <span className="bs-tree__op" aria-label={OP_LABEL[feature.op]}>{OP_ICON[feature.op]}</span>
                <span className="bs-tree__name">{feature.name}</span>
                <span className="bs-tree__meta">{feature.type}{feature.repeat ? ` ×${feature.repeat.count}` : ""}{feature.radial ? ` ◎${feature.radial.count}` : ""}{feature.mirror?.length ? " ⇋" : ""}</span>
              </button>
              <span className="bs-tree__tools">
                <button className="bs-icon" onClick={() => move(index, -1)} disabled={index === 0} aria-label="Move up">↑</button>
                <button className="bs-icon" onClick={() => move(index, 1)} disabled={index === part.features.length - 1} aria-label="Move down">↓</button>
                <button className="bs-icon" aria-label="Duplicate shape" onClick={() => {
                  const copy = { ...structuredClone(feature), id: uid("f"), name: `${feature.name} copy` };
                  const next = [...part.features];
                  next.splice(index + 1, 0, copy);
                  onChange({ ...part, features: next });
                  onActivate(copy.id);
                }}>⧉</button>
                <button className="bs-icon bs-icon--danger" aria-label="Delete shape" disabled={part.features.length === 1} onClick={() => {
                  onChange({ ...part, features: part.features.filter((f) => f.id !== feature.id) });
                  if (feature.id === activeFeatureId) onActivate(null);
                }}>×</button>
              </span>
            </li>
          ))}
        </ol>
        <div className="bs-shapes" role="group" aria-label="Add a shape">
          {SHAPES.map((shape) => (
            <button key={shape.type} className="bs-shape" onClick={() => addShape(shape.type)} title={shape.hint}>+ {shape.label}</button>
          ))}
        </div>
      </section>

      {active && (
        <section className="bs-section bs-section--active">
          <div className="bs-section__head">
            <h3>{active.name}</h3>
            <span className="bs-muted">shape {activeIndex + 1} · {active.type}</span>
          </div>
          <label className="bs-field"><span>Name</span><input value={active.name} onChange={(e) => setFeature(active.id, { name: e.target.value })} /></label>
          <div className="segmented bs-op" role="group" aria-label="What this shape does">
            {(["add", "cut", "intersect"] as FeatureOp[]).map((op) => (
              <button key={op} aria-pressed={active.op === op} disabled={activeIndex === 0 && op !== "add"} onClick={() => setFeature(active.id, { op })}
                title={activeIndex === 0 && op !== "add" ? "The first shape has to add material" : undefined}>
                {OP_ICON[op]} {OP_LABEL[op]}
              </button>
            ))}
          </div>

          {SIZE_FIELDS[active.type].length > 0 && (
            <div className="bs-grid3">
              {SIZE_FIELDS[active.type].map((field) => (
                <Num key={field.key} label={field.label} min={field.key === "r2" ? 0 : 0.1} step={0.5} value={active.size[field.key] ?? 0}
                  onChange={(v) => setFeature(active.id, { size: { ...active.size, [field.key]: v } })} />
              ))}
            </div>
          )}

          {(active.type === "extrude" || active.type === "revolve") && (
            <div className="bs-profile">
              <div className="bs-vec__label">{active.type === "extrude" ? "Outline points (x, z in mm)" : "Profile points (radius, height in mm)"}</div>
              <div className="bs-chips">
                {Object.entries(PROFILE_PRESETS).filter(([, p]) => p.for === active.type).map(([key, preset]) => (
                  <button key={key} className="chip" onClick={() => { setFeature(active.id, { profile: preset.points }); setProfileText(null); }}>{preset.label}</button>
                ))}
              </div>
              <textarea
                rows={5}
                spellCheck={false}
                value={profileText?.id === active.id ? profileText.text : (active.profile ?? []).map(([a, b]) => `${a}, ${b}`).join("\n")}
                onChange={(e) => {
                  setProfileText({ id: active.id, text: e.target.value });
                  const points = e.target.value.split("\n").map((line) => line.split(/[,\s]+/).filter(Boolean).map(Number))
                    .filter((pair) => pair.length >= 2 && pair.every(Number.isFinite)).map(([a, b]) => [a, b] as [number, number]);
                  if (points.length >= 3) setFeature(active.id, { profile: points });
                }}
                onBlur={() => setProfileText(null)}
                aria-label="Outline points, one per line"
              />
            </div>
          )}

          <Vec label="Position (mm)" value={active.at} onChange={(at) => setFeature(active.id, { at })} />
          <Vec label="Rotation (degrees)" value={active.rot} step={15} onChange={(rot) => setFeature(active.id, { rot })} />

          <div className="bs-grid3">
            <Num label="Round edges" min={0} step={0.5} value={active.round} title="Softens this shape's own edges" onChange={(round) => setFeature(active.id, { round })} />
            <Num label="Fillet blend" min={0} step={0.5} value={active.blend} title="Rounds the seam where this shape meets the shapes above it" onChange={(blend) => setFeature(active.id, { blend })} />
            {(active.type === "cylinder" || active.type === "cone" || active.type === "pipe") && (
              <Num label="Sides (0 = round)" min={0} step={1} value={active.sides ?? 0} title="6 makes a hex" onChange={(sides) => setFeature(active.id, { sides: sides >= 3 ? Math.round(sides) : undefined })} />
            )}
          </div>

          <details className="bs-details" open={Boolean(active.repeat || active.radial || active.mirror?.length)}>
            <summary>Patterns — repeat, ring, mirror</summary>
            <div className="bs-grid3">
              <Num label="Repeat count" min={1} step={1} value={active.repeat?.count ?? 1}
                onChange={(count) => setFeature(active.id, { repeat: count > 1 ? { count: Math.round(count), step: active.repeat?.step ?? [10, 0, 0] } : undefined })} />
            </div>
            {active.repeat && <Vec label="Repeat step (mm)" value={active.repeat.step} onChange={(step) => setFeature(active.id, { repeat: { ...active.repeat!, step } })} />}
            <div className="bs-grid3">
              <Num label="Ring count" min={1} step={1} value={active.radial?.count ?? 1}
                onChange={(count) => setFeature(active.id, { radial: count > 1 ? { count: Math.round(count), axis: active.radial?.axis ?? "y", radius: active.radial?.radius ?? 20 } : undefined })} />
              {active.radial && (
                <>
                  <label className="bs-num"><span>Around</span>
                    <select value={active.radial.axis} onChange={(e) => setFeature(active.id, { radial: { ...active.radial!, axis: e.target.value as "x" | "y" | "z" } })}>
                      <option value="y">Y (up)</option><option value="x">X</option><option value="z">Z</option>
                    </select>
                  </label>
                  <Num label="Ring radius" min={0} step={1} value={active.radial.radius} onChange={(radius) => setFeature(active.id, { radial: { ...active.radial!, radius } })} />
                </>
              )}
            </div>
            <div className="bs-mirror" role="group" aria-label="Mirror across">
              <span className="bs-vec__label">Mirror across</span>
              {(["x", "y", "z"] as const).map((axis) => {
                const on = active.mirror?.includes(axis) ?? false;
                return (
                  <button key={axis} className="chip" aria-pressed={on} onClick={() => {
                    const next = on ? (active.mirror ?? []).filter((a) => a !== axis) : [...(active.mirror ?? []), axis];
                    setFeature(active.id, { mirror: next.length ? next : undefined });
                  }}>{axis.toUpperCase()}</button>
                );
              })}
            </div>
          </details>

          <label className="bs-field"><span>What this shape is for (becomes the tutorial text)</span>
            <input value={active.note} onChange={(e) => setFeature(active.id, { note: e.target.value })} placeholder="e.g. Clearance for the USB-C plug" />
          </label>
        </section>
      )}

      <section className="bs-section">
        <div className="bs-section__head"><h3>Whole part</h3></div>
        <div className="bs-grid3">
          <Num label="Hollow wall (0 = solid)" min={0} step={0.5} value={part.shell?.thickness ?? 0}
            title="Keeps the outside and hollows the inside to this wall thickness"
            onChange={(thickness) => onChange({ ...part, shell: thickness > 0 ? { thickness } : undefined })} />
        </div>
        <details className="bs-details" open={part.pins.length > 0}>
          <summary>Pins and connection points ({part.pins.length})</summary>
          {part.pins.map((pin) => (
            <div className="bs-pinrow" key={pin.id}>
              <span className="bs-pin-dot" style={{ background: PIN_COLORS[pin.kind] }} aria-hidden />
              <input className="bs-pinrow__name" value={pin.name} onChange={(e) => setPin(pin.id, { name: e.target.value })} aria-label="Pin name" />
              <select value={pin.kind} onChange={(e) => setPin(pin.id, { kind: e.target.value as PinKind })} aria-label="Pin kind">
                {Object.keys(PIN_COLORS).map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
              <Num label="V" step={0.1} value={pin.voltage} onChange={(voltage) => setPin(pin.id, { voltage })} />
              <button className="bs-icon bs-icon--danger" aria-label={`Delete pin ${pin.name}`} onClick={() => onChange({ ...part, pins: part.pins.filter((p) => p.id !== pin.id) })}>×</button>
              <Vec label="At" value={pin.at} step={0.5} onChange={(at) => setPin(pin.id, { at })} />
            </div>
          ))}
          <button className="btn btn-secondary btn-sm" onClick={() => onChange({
            ...part,
            pins: [...part.pins, { id: uid("p"), name: `Pin ${part.pins.length + 1}`, kind: "digital", direction: "bidir", at: [0, 0, 0], voltage: 3.3, required: false, note: "" }],
          })}>+ Add pin</button>
        </details>
      </section>

      <div className="bs-editor__footer">
        <button className="btn btn-primary" disabled={busy} onClick={() => onSave(false)}>{isNew ? "Save part" : "Save changes"}</button>
        {isNew && <button className="btn btn-secondary" disabled={busy} onClick={() => onSave(true)}>Save and place</button>}
        {!isNew && <button className="btn btn-secondary" disabled={busy} onClick={onSaveToLibrary} title="Keep it for other builds">Save to library</button>}
        <button className="btn btn-ghost" onClick={onCancel}>Close</button>
      </div>
    </div>
  );
}
