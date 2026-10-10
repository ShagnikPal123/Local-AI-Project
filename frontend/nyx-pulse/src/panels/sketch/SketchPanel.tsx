/** The Create tab (sketch_studio.py, UPDATE_IDEAS U2): draw, and Nyx draws with you.
 *
 * The owner: "add create tab for images where the user can draw and the AI helps and can scan to make the image
 * better with a bar for what the user wants the AI to draw."
 *
 * Everything on the canvas is a list of strokes and shapes, so undo takes back exactly one thing — one pen stroke
 * or one whole thing Nyx drew. Nyx's drawing arrives as checked shape data (never code) and is drawn here.
 */

import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import { api, uploadFile } from "../../api";
import "./sketch.css";

const W = 1000;
const H = 700;
type Pt = [number, number];
interface Shape {
  kind: "line" | "path" | "rect" | "ellipse" | "polygon" | "text";
  points?: Pt[]; stroke?: string; fill?: string; width?: number; smooth?: boolean;
  x?: number; y?: number; w?: number; h?: number; radius?: number;
  cx?: number; cy?: number; rx?: number; ry?: number; text?: string; size?: number;
}
/** One undoable thing: a stroke the owner drew, or everything Nyx added at once. */
interface Layer { by: "you" | "nyx"; shapes: Shape[]; erase?: boolean; under?: boolean }

const COLOURS = ["#111111", "#ffffff", "#e5484d", "#f76b15", "#ffd60a", "#30a46c", "#3e63dd", "#8e4ec6", "#e93d82", "#8d5b3a"];

function drawShape(ctx: CanvasRenderingContext2D, s: Shape, erase = false) {
  ctx.save();
  ctx.globalCompositeOperation = erase ? "destination-out" : "source-over";
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.lineWidth = s.width ?? 3;
  ctx.strokeStyle = s.stroke || "#111111";
  ctx.fillStyle = s.fill || "transparent";
  const finish = () => { if (s.fill) ctx.fill(); if (s.stroke !== "" && (s.width ?? 1) > 0) ctx.stroke(); };
  if ((s.kind === "line" || s.kind === "path" || s.kind === "polygon") && s.points && s.points.length > 1) {
    const p = s.points;
    ctx.beginPath();
    ctx.moveTo(p[0][0], p[0][1]);
    if (s.smooth && p.length > 2) {
      for (let i = 1; i < p.length - 1; i++) {
        const mx = (p[i][0] + p[i + 1][0]) / 2;
        const my = (p[i][1] + p[i + 1][1]) / 2;
        ctx.quadraticCurveTo(p[i][0], p[i][1], mx, my);
      }
      ctx.lineTo(p[p.length - 1][0], p[p.length - 1][1]);
    } else {
      for (let i = 1; i < p.length; i++) ctx.lineTo(p[i][0], p[i][1]);
    }
    if (s.kind === "polygon") ctx.closePath();
    if (s.kind === "line") ctx.stroke(); else finish();
  } else if (s.kind === "rect") {
    ctx.beginPath();
    const r = Math.min(s.radius ?? 0, (s.w ?? 0) / 2, (s.h ?? 0) / 2);
    if (r > 0 && "roundRect" in ctx) (ctx as CanvasRenderingContext2D & { roundRect: (...a: number[]) => void }).roundRect(s.x ?? 0, s.y ?? 0, s.w ?? 0, s.h ?? 0, r);
    else ctx.rect(s.x ?? 0, s.y ?? 0, s.w ?? 0, s.h ?? 0);
    finish();
  } else if (s.kind === "ellipse") {
    ctx.beginPath();
    ctx.ellipse(s.cx ?? 0, s.cy ?? 0, s.rx ?? 1, s.ry ?? 1, 0, 0, Math.PI * 2);
    finish();
  } else if (s.kind === "text" && s.text) {
    ctx.fillStyle = s.fill || "#111111";
    ctx.font = `600 ${s.size ?? 28}px system-ui, sans-serif`;
    ctx.textBaseline = "top";
    ctx.fillText(s.text, s.x ?? 0, s.y ?? 0);
  }
  ctx.restore();
}

export function SketchPanel() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [layers, setLayers] = useState<Layer[]>([]);
  const [redo, setRedo] = useState<Layer[]>([]);
  const [colour, setColour] = useState("#111111");
  const [size, setSize] = useState(6);
  const [tool, setTool] = useState<"pen" | "eraser">("pen");
  const [paper, setPaper] = useState("#ffffff");
  const [ask, setAsk] = useState("");
  const [busy, setBusy] = useState<"" | "draw" | "scan" | "render" | "save" | "tab">("");
  const [note, setNote] = useState("");
  const [scanned, setScanned] = useState<{ sees: string; suggestions: string[]; model: string } | null>(null);
  const [picture, setPicture] = useState<{ image: string; model: string } | null>(null);
  const [saved, setSaved] = useState<{ id: string; name: string }[]>([]);
  const live = useRef<Layer | null>(null);
  /** A saved drawing that was opened: drawn under every layer, so new strokes still undo one by one. */
  const [base, setBase] = useState<HTMLImageElement | null>(null);

  const paint = useCallback(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);
    if (base) ctx.drawImage(base, 0, 0, W, H);
    // Backgrounds Nyx adds go under everything drawn so far; the rest stacks in the order it was added.
    for (const layer of layers) if (layer.under) for (const s of layer.shapes) drawShape(ctx, s);
    for (const layer of layers) if (!layer.under) for (const s of layer.shapes) drawShape(ctx, s, layer.erase);
    if (live.current) for (const s of live.current.shapes) drawShape(ctx, s, live.current.erase);
    ctx.save();                                   // the paper goes under everything, erased parts included
    ctx.globalCompositeOperation = "destination-over";
    ctx.fillStyle = paper;
    ctx.fillRect(0, 0, W, H);
    ctx.restore();
  }, [layers, paper, base]);
  useEffect(() => { paint(); }, [paint]);

  const loadSaved = useCallback(async () => {
    const r = await api.get<{ sketches: { id: string; name: string }[] }>("/api/sketch/saved");
    if (r.ok) setSaved(r.data.sketches);
  }, []);
  useEffect(() => { void loadSaved(); }, [loadSaved]);

  const at = (e: PointerEvent<HTMLCanvasElement>): Pt => {
    const box = e.currentTarget.getBoundingClientRect();
    return [Math.round(((e.clientX - box.left) / box.width) * W), Math.round(((e.clientY - box.top) / box.height) * H)];
  };
  const down = (e: PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    live.current = { by: "you", erase: tool === "eraser",
      shapes: [{ kind: "path", points: [at(e), at(e)], stroke: colour, width: tool === "eraser" ? size * 3 : size, smooth: true }] };
    paint();
  };
  const move = (e: PointerEvent<HTMLCanvasElement>) => {
    if (!live.current) return;
    live.current.shapes[0].points!.push(at(e));
    paint();
  };
  const up = () => {
    if (!live.current) return;
    const done = live.current;
    live.current = null;
    setLayers((l) => [...l, done]);
    setRedo([]);
  };

  const snapshot = () => canvas.current?.toDataURL("image/png") ?? "";
  const describe = () => (scanned?.sees ? scanned.sees : layers.length ? `${layers.length} strokes and shapes` : "");

  const nyxDraws = async () => {
    if (!ask.trim()) { setNote("Say what Nyx should draw in the bar first."); return; }
    setBusy("draw"); setNote("");
    const r = await api.post<{ shapes: Shape[]; say: string; model: string }>("/api/sketch/draw", { request: ask, existing: describe() }, 180000);
    setBusy("");
    if (!r.ok) { setNote(r.error); return; }
    setLayers((l) => [...l, { by: "nyx", shapes: r.data.shapes }]);
    setRedo([]);
    setNote(`${r.data.say || "Drawn."} (${r.data.shapes.length} shapes · ${r.data.model})`);
  };

  const doScan = async () => {
    setBusy("scan"); setNote("");
    const r = await api.post<{ sees: string; suggestions: string[]; shapes: Shape[]; under: Shape[]; model: string }>("/api/sketch/scan", { image: snapshot(), request: ask }, 180000);
    setBusy("");
    if (!r.ok) { setNote(r.error); return; }
    setScanned(r.data);
    const added: Layer[] = [];
    if (r.data.under.length) added.push({ by: "nyx", shapes: r.data.under, under: true });
    if (r.data.shapes.length) added.push({ by: "nyx", shapes: r.data.shapes });
    if (added.length) {
      setLayers((l) => [...l, ...added]);
      setRedo([]);
    }
    const count = r.data.shapes.length + r.data.under.length;
    setNote(count ? `Added ${count} improvements${r.data.under.length ? " (backgrounds go underneath)" : ""} — Undo takes them back.` : "Nothing to add this time.");
  };

  const makePicture = async () => {
    setBusy("render"); setNote("");
    const r = await api.post<{ image: string; model: string }>("/api/sketch/render", { request: ask, sees: scanned?.sees ?? "" }, 240000);
    setBusy("");
    if (!r.ok) { setNote(r.error); return; }
    setPicture(r.data);
  };

  const save = async () => {
    setBusy("save");
    const r = await api.post<{ id: string; name: string }>("/api/sketch/saved", { image: snapshot(), name: ask.trim().slice(0, 40) || "Drawing" });
    setBusy("");
    setNote(r.ok ? "Saved." : r.error);
    if (r.ok) void loadSaved();
  };

  /** The drawing becomes a tab of its own: the picture (uploaded, so it goes through the file checks) and notes. */
  const makeTab = async () => {
    setBusy("tab"); setNote("");
    const blob = await new Promise<Blob | null>((done) => {
      if (canvas.current) canvas.current.toBlob(done, "image/png"); else done(null);
    });
    if (!blob) { setBusy(""); setNote("Nothing to put in a tab yet."); return; }
    const name = ask.trim().slice(0, 40) || "My drawing";
    const upload = await uploadFile(new File([blob], `${name.replace(/[^a-z0-9]+/gi, "-") || "drawing"}.png`, { type: "image/png" }));
    if (!upload.ok) { setBusy(""); setNote(upload.error); return; }
    const tab = await api.post<{ tab: { id: string } }>("/api/tabs", {
      label: name, icon: "ph-image", description: "Made from a drawing in Create.",
      blocks: [
        { type: "image", title: name, config: { src: `/api/uploads/${upload.data.id}`, caption: scanned?.sees ?? "", fit: "contain", layout: { span: 2 } } },
        { type: "notes", title: "Notes" },
      ],
      theme: { columns: 3 },
    });
    setBusy("");
    if (!tab.ok) { setNote(tab.error); return; }
    window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: tab.data.tab.id } }));
  };

  const open = async (id: string) => {
    const r = await api.get<{ image: string }>(`/api/sketch/saved/${id}`);
    if (!r.ok) { setNote(r.error); return; }
    const img = new Image();
    img.onload = () => {
      setBase(img);
      setLayers([]);
      setRedo([]);
      setNote("Opened. Draw on top; Undo takes back what you add now.");
    };
    img.src = r.data.image;
  };

  return (
    <div className="sk">
      <header className="sk-head">
        <div>
          <h1>Create</h1>
          <p className="sk-muted">Draw, and Nyx draws with you. Scan looks at your drawing and adds what would make it better.</p>
        </div>
      </header>

      <form className="sk-bar" onSubmit={(e) => { e.preventDefault(); void nyxDraws(); }}>
        <input value={ask} onChange={(e) => setAsk(e.target.value)} placeholder="What should Nyx draw? — “a lighthouse at sunset”, “add a cat on the sofa”…" aria-label="What Nyx should draw" />
        <button className="btn btn-primary" disabled={!!busy}>{busy === "draw" ? "Drawing…" : "Nyx Draws"}</button>
        <button type="button" className="btn btn-secondary" disabled={!!busy} onClick={() => void doScan()}>{busy === "scan" ? "Scanning…" : "Scan & Improve"}</button>
        <button type="button" className="btn btn-secondary" disabled={!!busy} onClick={() => void makePicture()}
                title="Uses your online image model: the description (not your drawing) leaves this PC.">
          {busy === "render" ? "Painting…" : "Make It a Picture"}
        </button>
      </form>

      <div className="sk-tools" role="toolbar" aria-label="Drawing tools">
        <button className={`sk-tool${tool === "pen" ? " is-on" : ""}`} onClick={() => setTool("pen")} aria-pressed={tool === "pen"}>Pen</button>
        <button className={`sk-tool${tool === "eraser" ? " is-on" : ""}`} onClick={() => setTool("eraser")} aria-pressed={tool === "eraser"}>Eraser</button>
        <span className="sk-swatches">
          {COLOURS.map((c) => (
            <button key={c} className={`sk-swatch${colour === c ? " is-on" : ""}`} style={{ background: c }} aria-label={`Colour ${c}`}
                    onClick={() => { setColour(c); setTool("pen"); }} />
          ))}
          <input type="color" value={colour} onChange={(e) => { setColour(e.target.value); setTool("pen"); }} aria-label="Any colour" />
        </span>
        <label className="sk-size">Size <input type="range" min={1} max={40} value={size} onChange={(e) => setSize(Number(e.target.value))} /></label>
        <label className="sk-size">Paper <input type="color" value={paper} onChange={(e) => setPaper(e.target.value)} /></label>
        <span className="sk-spacer" />
        <button className="sk-tool" disabled={!layers.length} onClick={() => { setRedo((r) => [layers[layers.length - 1], ...r]); setLayers((l) => l.slice(0, -1)); }}>Undo</button>
        <button className="sk-tool" disabled={!redo.length} onClick={() => { setLayers((l) => [...l, redo[0]]); setRedo((r) => r.slice(1)); }}>Redo</button>
        <button className="sk-tool" disabled={!layers.length && !base} onClick={() => { setLayers([]); setRedo([]); setScanned(null); setBase(null); }}>Clear</button>
        <button className="sk-tool" disabled={busy === "save"} onClick={() => void save()}>Save</button>
        <button className="sk-tool" disabled={!!busy} onClick={() => void makeTab()}>{busy === "tab" ? "Making…" : "Make It a Tab"}</button>
        <a className="sk-tool" href="#" onClick={(e) => { e.currentTarget.href = snapshot(); }} download="drawing.png">Download PNG</a>
      </div>

      <div className="sk-stage">
        <canvas ref={canvas} width={W} height={H} className={`sk-canvas sk-canvas--${tool}`} aria-label="Drawing canvas"
                onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} />
        <aside className="sk-side">
          {note && <p className="sk-note" role="status">{note}</p>}
          {scanned && (
            <div className="sk-card">
              <b>Nyx sees</b>
              <p>{scanned.sees}</p>
              {scanned.suggestions.length > 0 && <ul>{scanned.suggestions.map((s) => <li key={s}>{s}</li>)}</ul>}
              <small className="sk-muted">{scanned.model}</small>
            </div>
          )}
          {picture && (
            <div className="sk-card">
              <b>The picture</b>
              <img src={picture.image} alt={`Painted from: ${ask || scanned?.sees || "your drawing"}`} />
              <small className="sk-muted">{picture.model} · <a href={picture.image} download="picture.png">Download</a></small>
            </div>
          )}
          {saved.length > 0 && (
            <div className="sk-card">
              <b>Saved drawings</b>
              <ul className="sk-saved">{saved.slice(0, 12).map((s) => <li key={s.id}><button className="sk-link" onClick={() => void open(s.id)}>{s.name}</button></li>)}</ul>
            </div>
          )}
          <p className="sk-muted">Layers: {layers.filter((l) => l.by === "you").length} yours · {layers.filter((l) => l.by === "nyx").length} Nyx's</p>
        </aside>
      </div>
    </div>
  );
}
