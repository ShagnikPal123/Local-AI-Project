/** The right-hand panel in Space and Circuit modes: whatever is selected, in detail. */

import { useState } from "react";
import { Markdown } from "../../components/chat/Markdown";
import { PIN_COLORS, type NetPoint, type Part, type Placement, type Selection, type Snapshot, type Vec3 } from "./types";

function NumberField({ label, value, onCommit, step = 1 }: { label: string; value: number; onCommit: (v: number) => void; step?: number }) {
  const [text, setText] = useState<string | null>(null);
  const commit = () => {
    if (text === null) return;
    const parsed = Number(text);
    if (text !== "" && Number.isFinite(parsed) && parsed !== value) onCommit(parsed);
    setText(null);
  };
  return (
    <label className="bs-num">
      <span>{label}</span>
      <input type="number" step={step} value={text ?? String(Math.round(value * 100) / 100)}
        onChange={(e) => setText(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setText(null); }} />
    </label>
  );
}

function VecField({ label, value, step, onCommit }: { label: string; value: Vec3; step?: number; onCommit: (v: Vec3) => void }) {
  return (
    <div className="bs-vec">
      <div className="bs-vec__label">{label}</div>
      {(["X", "Y", "Z"] as const).map((axis, i) => (
        <NumberField key={axis} label={axis} step={step} value={value[i]} onCommit={(v) => {
          const next = [...value] as Vec3;
          next[i] = v;
          onCommit(next);
        }} />
      ))}
    </div>
  );
}

export interface InspectorProps {
  snapshot: Snapshot;
  mode: "space" | "circuit";
  selection: Selection;
  multi: string[];
  pendingPin: NetPoint | null;
  busy: boolean;
  explain: { partId: string; text: string; model: string } | null;
  onSelect: (selection: Selection) => void;
  onPickPin: (point: NetPoint) => void;
  onCancelPin: () => void;
  onUpdatePlacement: (id: string, fields: Partial<Placement>) => void;
  onDeletePlacement: (id: string) => void;
  onPlaceAnother: (partId: string) => void;
  onEditPart: (partId: string) => void;
  onSaveToLibrary: (partId: string) => void;
  onExplainPart: (partId: string) => void;
  onCombine: (name: string) => void;
  onJoin: (kind: string) => void;
  onClearMulti: () => void;
  onDisconnect: (netId: string, point?: NetPoint) => void;
  onRenameNet: (netId: string, name: string) => void;
  onUpdateProject: (fields: { name?: string; goal?: string; space?: Snapshot["project"]["space"] }) => void;
  onAskWiring: () => void;
  onSeatOnPlate: (id: string) => void;
}

export function Inspector(props: InspectorProps) {
  const { snapshot, selection, multi, mode } = props;
  const project = snapshot.project;
  const parts = new Map(project.parts.map((p) => [p.id, p]));
  const [combineName, setCombineName] = useState("");
  const [jointKind, setJointKind] = useState("screw");
  const [pinFilter, setPinFilter] = useState("");

  const placement = selection.kind === "placement" ? project.placements.find((p) => p.id === selection.id)
    : selection.kind === "pin" ? project.placements.find((p) => p.id === selection.placement) : undefined;
  const part: Part | undefined = placement ? parts.get(placement.part_id) : undefined;
  const net = selection.kind === "net" ? project.nets.find((n) => n.id === selection.id) : undefined;

  const pinLabel = (point: NetPoint) => {
    const pl = project.placements.find((p) => p.id === point.placement);
    const pin = pl && parts.get(pl.part_id)?.pins.find((p) => p.id === point.pin);
    return pl && pin ? `${pl.name || parts.get(pl.part_id)?.name}.${pin.name}` : "(gone)";
  };
  const netsOf = (point: NetPoint) => project.nets.filter((n) => n.points.some((p) => p.placement === point.placement && p.pin === point.pin));

  // --- several pieces selected: combine or join them ---------------------------------
  if (mode === "space" && multi.length >= 2) {
    const names = multi.map((id) => project.placements.find((p) => p.id === id)).filter(Boolean).map((p) => p!.name || parts.get(p!.part_id)?.name);
    const wires = project.nets.filter((n) => n.points.some((pt) => multi.includes(pt.placement))).length;
    return (
      <div className="bs-inspector">
        <section className="bs-section">
          <div className="bs-section__head"><h3>{multi.length} pieces selected</h3></div>
          <p className="bs-muted">{names.join(", ")}</p>
        </section>
        <section className="bs-section">
          <div className="bs-section__head"><h3>Combine into one part</h3></div>
          <p className="bs-muted">Bakes them into a single part you can edit, print, save and reuse. Their pins come along.{wires ? ` ${wires} wire${wires === 1 ? "" : "s"} attached to these pieces will be removed.` : ""}</p>
          <label className="bs-field"><span>New part name</span><input value={combineName} placeholder="e.g. Pi with fan and bracket" onChange={(e) => setCombineName(e.target.value)} /></label>
          <button className="btn btn-primary" disabled={props.busy} onClick={() => props.onCombine(combineName.trim())}>Combine {multi.length} pieces</button>
        </section>
        <section className="bs-section">
          <div className="bs-section__head"><h3>Join them</h3></div>
          <p className="bs-muted">Keeps them separate but records how they attach. Joined pieces may touch without a warning.</p>
          <div className="bs-row">
            <select value={jointKind} onChange={(e) => setJointKind(e.target.value)} aria-label="How they attach">
              {["screw", "stack", "fixed", "clip", "hinge", "slide"].map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <button className="btn btn-secondary" disabled={props.busy || multi.length !== 2} onClick={() => props.onJoin(jointKind)} title={multi.length !== 2 ? "Select exactly two pieces to join" : undefined}>Join</button>
          </div>
        </section>
        <button className="btn btn-ghost" onClick={props.onClearMulti}>Clear selection</button>
      </div>
    );
  }

  // --- circuit mode --------------------------------------------------------------------
  if (mode === "circuit") {
    const words = pinFilter.toLowerCase();
    return (
      <div className="bs-inspector">
        <section className="bs-section">
          <div className="bs-section__head"><h3>Wire the circuit</h3></div>
          {props.pendingPin ? (
            <div className="bs-pending">
              <span>From <b>{pinLabel(props.pendingPin)}</b> — now pick the other end.</span>
              <button className="bs-link" onClick={props.onCancelPin}>Cancel</button>
            </div>
          ) : (
            <p className="bs-muted">Pick a pin (in the list or on a part), then a second pin. Wires join into nets, and the checks flag shorts, voltage mismatches and overloaded supplies as you go.</p>
          )}
          <button className="btn btn-secondary btn-sm" onClick={props.onAskWiring} disabled={props.busy || project.placements.length < 2}>Ask Nyx to wire it</button>
        </section>

        <section className="bs-section">
          <div className="bs-section__head"><h3>Nets</h3><span className="bs-muted">{project.nets.length}</span></div>
          {!project.nets.length && <p className="bs-muted">No wires yet.</p>}
          {project.nets.map((n) => (
            <div key={n.id} className={`bs-net${selection.kind === "net" && selection.id === n.id ? " is-active" : ""}`}>
              <button className="bs-net__main" onClick={() => props.onSelect({ kind: "net", id: n.id })}>
                <span className="bs-pin-dot" style={{ background: n.color }} aria-hidden />
                <span className="bs-item__name">{n.name}</span>
                <span className="bs-item__meta">{n.kind}{n.voltage ? ` · ${n.voltage} V` : ""} · {n.points.length} pins</span>
              </button>
              <button className="bs-icon bs-icon--danger" aria-label={`Delete wire ${n.name}`} onClick={() => props.onDisconnect(n.id)}>×</button>
            </div>
          ))}
        </section>

        <section className="bs-section">
          <div className="bs-section__head"><h3>Pins</h3></div>
          <input className="bs-search" type="search" placeholder="Filter: 5V, GND, SDA…" value={pinFilter} onChange={(e) => setPinFilter(e.target.value)} aria-label="Filter pins" />
          {project.placements.map((pl) => {
            const p = parts.get(pl.part_id);
            const pins = (p?.pins ?? []).filter((pin) => !words || `${pin.name} ${pin.kind}`.toLowerCase().includes(words));
            if (!p || !pins.length) return null;
            return (
              <details key={pl.id} className="bs-details" open={placement?.id === pl.id || Boolean(words)}>
                <summary>{pl.name || p.name} <span className="bs-muted">({pins.length})</span></summary>
                <div className="bs-pins">
                  {pins.map((pin) => {
                    const point = { placement: pl.id, pin: pin.id };
                    const wired = netsOf(point).length > 0;
                    const pending = props.pendingPin?.placement === pl.id && props.pendingPin.pin === pin.id;
                    return (
                      <button key={pin.id} className={`bs-pinbtn${pending ? " is-pending" : ""}${wired ? " is-wired" : ""}`} onClick={() => props.onPickPin(point)}
                        title={`${pin.kind}${pin.voltage ? ` ${pin.voltage} V` : ""}${pin.required ? " · needs connecting" : ""}${wired ? " · wired" : ""}`}>
                        <span className="bs-pin-dot" style={{ background: PIN_COLORS[pin.kind] }} aria-hidden />
                        {pin.name}{pin.required && !wired ? " •" : ""}
                      </button>
                    );
                  })}
                </div>
              </details>
            );
          })}
        </section>
      </div>
    );
  }

  // --- a wire ------------------------------------------------------------------------------
  if (net) {
    return (
      <div className="bs-inspector">
        <section className="bs-section">
          <div className="bs-section__head"><h3>Wire</h3><span className="bs-pin-dot" style={{ background: net.color }} aria-hidden /></div>
          <label className="bs-field"><span>Name</span>
            <input defaultValue={net.name} key={net.id} onBlur={(e) => { if (e.target.value.trim() && e.target.value !== net.name) props.onRenameNet(net.id, e.target.value.trim()); }} />
          </label>
          <p className="bs-muted">{net.kind}{net.voltage ? ` · ${net.voltage} V` : ""}</p>
          {net.points.map((point) => (
            <div key={`${point.placement}-${point.pin}`} className="bs-endpoint">
              <span>{pinLabel(point)}</span>
              <button className="bs-link bs-link--danger" onClick={() => props.onDisconnect(net.id, point)}>Unhook</button>
            </div>
          ))}
          <button className="btn btn-secondary" onClick={() => props.onDisconnect(net.id)}>Delete wire</button>
        </section>
      </div>
    );
  }

  // --- one piece ---------------------------------------------------------------------------
  if (placement && part) {
    const pin = selection.kind === "pin" ? part.pins.find((p) => p.id === selection.pin) : undefined;
    const box = snapshot.bounds[placement.id];
    const specs = Object.entries(part.specs).filter(([, v]) => v !== "" && v !== 0);
    return (
      <div className="bs-inspector">
        <section className="bs-section">
          <div className="bs-section__head">
            <span className="bs-swatch" style={{ background: part.color }} aria-hidden />
            <h3>{placement.name || part.name}</h3>
          </div>
          {part.summary && <p className="bs-summary">{part.summary}</p>}
          {box && <p className="bs-muted">{box.size.map((v) => v.toFixed(1)).join(" × ")} mm (X × Y × Z){part.material ? ` · ${part.material}` : ""}</p>}
          {specs.length > 0 && (
            <dl className="bs-specs">
              {specs.slice(0, 8).map(([key, value]) => (<div key={key}><dt>{key.replace(/_/g, " ")}</dt><dd>{String(value)}</dd></div>))}
            </dl>
          )}
        </section>

        {pin && (
          <section className="bs-section bs-section--active">
            <div className="bs-section__head"><span className="bs-pin-dot" style={{ background: PIN_COLORS[pin.kind] }} aria-hidden /><h3>Pin {pin.name}</h3></div>
            <p className="bs-muted">{pin.kind} · {pin.direction}{pin.voltage ? ` · ${pin.voltage} V` : ""}{pin.required ? " · needs connecting" : ""}</p>
            {netsOf({ placement: placement.id, pin: pin.id }).map((n) => <p key={n.id} className="bs-muted">On wire <b>{n.name}</b></p>)}
            <button className="btn btn-secondary btn-sm" onClick={() => props.onPickPin({ placement: placement.id, pin: pin.id })}>Wire from this pin</button>
          </section>
        )}

        <section className="bs-section">
          <div className="bs-section__head"><h3>Placement</h3>{placement.locked && <span className="chip">Locked</span>}</div>
          <label className="bs-field"><span>Label</span>
            <input defaultValue={placement.name} key={placement.id} onBlur={(e) => { if (e.target.value !== placement.name) props.onUpdatePlacement(placement.id, { name: e.target.value }); }} />
          </label>
          <VecField label="Position (mm)" value={placement.at} onCommit={(at) => props.onUpdatePlacement(placement.id, { at })} />
          <VecField label="Rotation (degrees)" step={15} value={placement.rot} onCommit={(rot) => props.onUpdatePlacement(placement.id, { rot })} />
          <div className="bs-row">
            <button className="btn btn-secondary btn-sm" onClick={() => props.onUpdatePlacement(placement.id, { rot: [placement.rot[0], (placement.rot[1] + 90) % 360, placement.rot[2]] })}>Turn 90°</button>
            <button className="btn btn-secondary btn-sm" onClick={() => props.onSeatOnPlate(placement.id)}>Sit on plate</button>
            <button className="btn btn-secondary btn-sm" onClick={() => props.onUpdatePlacement(placement.id, { locked: !placement.locked })}>{placement.locked ? "Unlock" : "Lock"}</button>
          </div>
        </section>

        <section className="bs-section">
          <div className="bs-actions">
            <button className="btn btn-secondary btn-sm" onClick={() => props.onEditPart(part.id)}>Edit part</button>
            <button className="btn btn-secondary btn-sm" disabled={props.busy} onClick={() => props.onPlaceAnother(part.id)}>Place another</button>
            <button className="btn btn-secondary btn-sm" disabled={props.busy} onClick={() => props.onSaveToLibrary(part.id)}>Save to library</button>
            <button className="btn btn-secondary btn-sm" disabled={props.busy} onClick={() => props.onExplainPart(part.id)}>Explain with Nyx</button>
            <button className="btn btn-danger btn-sm" onClick={() => props.onDeletePlacement(placement.id)}>Remove</button>
          </div>
          <p className="bs-muted bs-hint">Shift-click more pieces to combine or join them.</p>
          {props.explain?.partId === part.id && (
            <div className="bs-answer"><Markdown text={props.explain.text} /><div className="bs-model">{props.explain.model}</div></div>
          )}
        </section>

        {part.pins.length > 0 && (
          <section className="bs-section">
            <details className="bs-details">
              <summary>Pins ({part.pins.length})</summary>
              <div className="bs-pins">
                {part.pins.map((p) => (
                  <button key={p.id} className="bs-pinbtn" onClick={() => props.onSelect({ kind: "pin", placement: placement.id, pin: p.id })}>
                    <span className="bs-pin-dot" style={{ background: PIN_COLORS[p.kind] }} aria-hidden />{p.name}
                  </button>
                ))}
              </div>
            </details>
          </section>
        )}
      </div>
    );
  }

  // --- nothing selected: the build itself ------------------------------------------------------
  return (
    <div className="bs-inspector">
      <section className="bs-section">
        <div className="bs-section__head"><h3>This build</h3></div>
        <label className="bs-field"><span>Name</span>
          <input defaultValue={project.name} key={`${project.id}-name`} onBlur={(e) => { if (e.target.value.trim() && e.target.value !== project.name) props.onUpdateProject({ name: e.target.value.trim() }); }} />
        </label>
        <label className="bs-field"><span>What it has to do</span>
          <textarea rows={3} defaultValue={project.goal} key={`${project.id}-goal`} placeholder="e.g. A quiet, cool enclosure that runs a local AI model on a Raspberry Pi 5"
            onBlur={(e) => { if (e.target.value !== project.goal) props.onUpdateProject({ goal: e.target.value }); }} />
        </label>
        <div className="bs-vec">
          <div className="bs-vec__label">Build space (mm) — your printer bed or enclosure</div>
          <NumberField label="W" value={project.space.width} onCommit={(width) => props.onUpdateProject({ space: { ...project.space, width } })} />
          <NumberField label="D" value={project.space.depth} onCommit={(depth) => props.onUpdateProject({ space: { ...project.space, depth } })} />
          <NumberField label="H" value={project.space.height} onCommit={(height) => props.onUpdateProject({ space: { ...project.space, height } })} />
        </div>
      </section>
      <section className="bs-section">
        <div className="bs-stats">
          <div><b>{project.placements.length}</b><span>pieces</span></div>
          <div><b>{project.parts.length}</b><span>parts</span></div>
          <div><b>{project.nets.length}</b><span>wires</span></div>
          <div><b>{snapshot.checks.filter((c) => c.level === "error").length}</b><span>errors</span></div>
        </div>
      </section>
      <section className="bs-section bs-tips">
        <div className="bs-section__head"><h3>How to drive it</h3></div>
        <ul>
          <li><b>Drag</b> to orbit, <b>right-drag</b> to pan, <b>scroll</b> to zoom.</li>
          <li><b>Click</b> a part to select it. <b>Shift-click</b> to select several and combine them.</li>
          <li><b>M</b> move, <b>R</b> rotate, <b>Esc</b> select. <b>F</b> frames the selection.</li>
          <li><b>Circuit</b> mode shows every pin; pick two to wire them.</li>
        </ul>
      </section>
    </div>
  );
}
