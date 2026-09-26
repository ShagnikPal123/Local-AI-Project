/** The diagram overlay (Request R14): what Nyx drew, over the chat, with a pen in your hand.
 *
 * "a new tab opens as an overlay and it can draw or pull from an image … Make sure it's pdf and drawing is available
 * and works." So: the diagram as SVG (laid out here — the server only ever sends data), a real picture beside it when
 * one was found, a drawing layer on top, and Save PNG / Save PDF / Put In Chat.
 *
 * It is a modal dialog: Escape closes it, focus starts inside it, and nothing behind it is reachable while it is open.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, authHeaders } from "../../api";
import { useReducedMotion } from "../../useReducedMotion";
import "./diagram.css";

export interface DiagramNode { id: string; label: string; sub: string; group: string; shape: string; level: number | null }
export interface DiagramEdge { from: string; to: string; label: string; style: string }
export interface DiagramGroup { id: string; label: string; color: number }
export interface DiagramImage { url: string; thumb: string; title: string; source: string; licence: string; by: string; where: string }
export interface Stroke { color: string; size: number; points: number[][] }
export interface Diagram {
  id: string; title: string; caption: string; kind: string; nodes: DiagramNode[]; edges: DiagramEdge[];
  groups: DiagramGroup[]; notes: string[]; image: DiagramImage | null; image_choices?: DiagramImage[];
  strokes: Stroke[]; request: string; source: string; created_at: number; helpers?: number;
}

const GROUP_COLORS = ["#a594ff", "#4cc9f0", "#5ee08f", "#f9a23b", "#ff7a8a", "#e6e15c", "#7fd4c1", "#9cc7ff"];
const PEN_COLORS = ["#f5f5f7", "#a594ff", "#5ee08f", "#f9a23b", "#ff7a8a", "#4cc9f0"];
const MIN_W = 1180;
const NODE_W = 188;
const NODE_H = 66;
const GAP_X = 84;
const GAP_Y = 20;
const SUB_GAP = 22;
/** Room above the boxes for the group headings and the top lane, and below them for the bottom lane. */
const TOP = 62;
const BOTTOM = 44;
/** A column taller than this wraps into a second one beside it, so a big diagram grows wide, not endlessly tall. */
const MAX_ROWS = 8;
/** What fits on one line of a box at these font sizes; the rest is in the box's tooltip. */
const LABEL_CHARS = 20;
const SUB_CHARS = 26;

interface Placed extends DiagramNode {
  x: number; y: number; w: number; h: number;
  /** The visual column and row it sits in, and the room either side of that column (where lines can run). */
  column: number; row: number; gapLeft: number; gapRight: number;
}
interface Route { d: string; x: number; y: number; anchor: "start" | "middle" }
interface Header { label: string; x: number }

/** Which column each node belongs in: its group for a map (and, inside a group, one step right for each box of the
 *  same group that points at it), its stage for a stack or timeline, its distance from the start for a flow. */
function baseColumns(diagram: Diagram): Map<string, number> {
  const nodes = diagram.nodes;
  const column = new Map<string, number>();
  const groups = diagram.groups.map((g) => g.label.toLowerCase());
  if ((diagram.kind === "map" || diagram.kind === "comparison") && groups.length >= 2) {
    const groupOf = new Map(nodes.map((node) => [node.id, Math.max(0, groups.indexOf((node.group || "").toLowerCase()))]));
    const depth = new Map<string, number>(nodes.map((node) => [node.id, 0]));
    const inside = diagram.edges.filter((e) => e.from !== e.to && groupOf.has(e.from) && groupOf.get(e.from) === groupOf.get(e.to));
    for (let pass = 0; pass < 4; pass += 1) {
      inside.forEach((e) => depth.set(e.to, Math.min(3, Math.max(depth.get(e.to) ?? 0, (depth.get(e.from) ?? 0) + 1))));
    }
    nodes.forEach((node) => column.set(node.id, (groupOf.get(node.id) ?? 0) * 10 + Math.min(3, node.level ?? depth.get(node.id) ?? 0)));
    return column;
  }
  if (diagram.kind === "stack" || diagram.kind === "timeline") {
    nodes.forEach((node, index) => {
      const fromGroup = groups.indexOf((node.group || "").toLowerCase());
      column.set(node.id, node.level ?? (fromGroup >= 0 ? fromGroup : Math.floor(index / Math.max(1, Math.ceil(nodes.length / 4)))));
    });
    return column;
  }
  // A flow: the longest path from a node that nothing points at.
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const incoming = new Map<string, number>(nodes.map((n) => [n.id, 0]));
  diagram.edges.forEach((e) => { if (byId.has(e.to)) incoming.set(e.to, (incoming.get(e.to) ?? 0) + 1); });
  const queue = nodes.filter((n) => (incoming.get(n.id) ?? 0) === 0).map((n) => n.id);
  if (!queue.length && nodes.length) queue.push(nodes[0].id);
  queue.forEach((id) => column.set(id, 0));
  const seen = new Set(queue);
  let guard = 0;
  while (queue.length && guard++ < 800) {
    const id = queue.shift()!;
    const here = column.get(id) ?? 0;
    diagram.edges.filter((e) => e.from === id).forEach((edge) => {
      const next = Math.min(12, Math.max(column.get(edge.to) ?? 0, here + 1));
      if (next > (column.get(edge.to) ?? -1)) column.set(edge.to, next);
      if (!seen.has(edge.to)) { seen.add(edge.to); queue.push(edge.to); }
    });
  }
  nodes.forEach((n, index) => { if (!column.has(n.id)) column.set(n.id, index % 3); });
  return column;
}

/** Place every node: columns left to right, tall columns wrapped into sub-columns, each column centred vertically. */
function layout(diagram: Diagram): { placed: Placed[]; height: number; width: number; headers: Header[] } {
  const column = baseColumns(diagram);
  const buckets = new Map<number, DiagramNode[]>();
  diagram.nodes.forEach((node) => {
    const key = column.get(node.id) ?? 0;
    buckets.set(key, [...(buckets.get(key) ?? []), node]);
  });
  const order = Array.from(buckets.keys()).sort((a, b) => a - b);
  const tallest = Math.min(MAX_ROWS, Math.max(1, ...Array.from(buckets.values(), (list) => list.length)));
  const height = Math.max(300, tallest * (NODE_H + GAP_Y) - GAP_Y + TOP + BOTTOM);
  const room = height - TOP - BOTTOM;
  const placed: Placed[] = [];
  let x = 40;
  let visual = 0;
  order.forEach((key) => {
    const list = buckets.get(key)!;
    const chunks = Math.ceil(list.length / MAX_ROWS);
    for (let chunk = 0; chunk < chunks; chunk += 1) {
      const part = list.slice(chunk * MAX_ROWS, (chunk + 1) * MAX_ROWS);
      const columnHeight = part.length * (NODE_H + GAP_Y) - GAP_Y;
      const top = TOP + (room - columnHeight) / 2;
      part.forEach((node, row) => {
        placed.push({ ...node, column: visual, row, w: NODE_W, h: NODE_H, x, y: top + row * (NODE_H + GAP_Y),
                      gapLeft: chunk > 0 ? SUB_GAP : GAP_X, gapRight: chunk < chunks - 1 ? SUB_GAP : GAP_X });
      });
      x += NODE_W + (chunk < chunks - 1 ? SUB_GAP : 0);
      visual += 1;
    }
    x += GAP_X;
  });
  const used = x - GAP_X + 40;
  const width = Math.max(MIN_W, used);
  const shift = used < MIN_W ? (MIN_W - used) / 2 : 0;          // a small diagram sits in the middle
  placed.forEach((node) => { node.x += shift; });
  // A map's columns are its groups, so each gets a heading instead of a tag on every box.
  const headers: Header[] = [];
  if ((diagram.kind === "map" || diagram.kind === "comparison") && diagram.groups.length >= 2) {
    diagram.groups.forEach((group) => {
      const xs = placed.filter((n) => (n.group || "").toLowerCase() === group.label.toLowerCase()).map((n) => n.x);
      if (xs.length) headers.push({ label: group.label, x: Math.min(...xs) });
    });
  }
  return { placed, height, width, headers };
}

/** A polyline with rounded corners, for the lines that travel along a lane. */
function rounded(points: number[][], radius = 10): string {
  let d = `M ${points[0][0]} ${points[0][1]}`;
  for (let i = 1; i < points.length - 1; i += 1) {
    const [px, py] = points[i - 1], [cx, cy] = points[i], [nx, ny] = points[i + 1];
    const inLen = Math.hypot(cx - px, cy - py), outLen = Math.hypot(nx - cx, ny - cy);
    const r = Math.min(radius, inLen / 2, outLen / 2);
    if (r < 0.5) { d += ` L ${cx} ${cy}`; continue; }
    d += ` L ${cx - ((cx - px) / inLen) * r} ${cy - ((cy - py) / inLen) * r}`
      + ` Q ${cx} ${cy} ${cx + ((nx - cx) / outLen) * r} ${cy + ((ny - cy) / outLen) * r}`;
  }
  const last = points[points.length - 1];
  return `${d} L ${last[0]} ${last[1]}`;
}

/** How a line gets from one box to another without running through the boxes in between. */
function route(a: Placed, b: Placed, height: number): Route {
  const x1 = a.x + a.w, y1 = a.y + a.h / 2;
  const x2 = b.x, y2 = b.y + b.h / 2;
  if (a.column === b.column) {
    if (Math.abs(a.row - b.row) === 1) {
      // Neighbours in one column: straight across the gap between them.
      const cx = a.x + a.w / 2;
      const [from, to] = b.row > a.row ? [a.y + a.h, b.y] : [a.y, b.y + b.h];
      return { d: `M ${cx} ${from} L ${cx} ${to}`, x: cx + 8, y: (from + to) / 2 + 4, anchor: "start" };
    }
    // Further apart in one column: bow out beside the boxes.
    const bow = x1 + 28 + Math.min(34, Math.abs(y2 - y1) * 0.06);
    return { d: `M ${x1} ${y1} C ${bow} ${y1}, ${bow} ${y2}, ${b.x + b.w} ${y2}`, x: bow + 4, y: (y1 + y2) / 2 + 4, anchor: "start" };
  }
  if (b.column === a.column + 1) {
    const dx = Math.max(36, (x2 - x1) * 0.5);
    return { d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`, x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 6, anchor: "middle" };
  }
  // Skipping columns, or going back: out into the gap, along a lane above the boxes (or below them), and in from
  // the left — so a long line never crosses a box.
  const lane = y2 <= height / 2 ? TOP - 22 : height - BOTTOM / 2;
  const ax = x1 + Math.min(a.gapRight, 80) / 2;
  const dx = x2 - Math.min(b.gapLeft, b.x, 80) / 2;
  return { d: rounded([[x1, y1], [ax, y1], [ax, lane], [dx, lane], [dx, y2], [x2, y2]]),
           x: (ax + dx) / 2, y: lane < height / 2 ? lane - 6 : lane + 14, anchor: "middle" };
}

/** A sub-label on at most two lines, cut with an ellipsis. */
function wrapSub(text: string, max: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const raw of text.split(/\s+/).filter(Boolean)) {
    const word = raw.length > max ? `${raw.slice(0, max - 1)}…` : raw;
    const next = line ? `${line} ${word}` : word;
    if (next.length <= max) { line = next; continue; }
    lines.push(line);
    line = word;
    if (lines.length === 2) { lines[1] = `${lines[1].replace(/[,;:·]$/, "")}…`; return lines; }
  }
  if (line) lines.push(line);
  return lines;
}

export function DiagramOverlay({ diagram, onClose, onChanged, onInsert }: {
  diagram: Diagram;
  onClose: () => void;
  onChanged?: (diagram: Diagram) => void;
  onInsert?: (uploadId: string, title: string) => void;
}) {
  const reduced = useReducedMotion();
  const [spec, setSpec] = useState<Diagram>(diagram);
  const [drawing, setDrawing] = useState(false);
  const [penColor, setPenColor] = useState(PEN_COLORS[1]);
  const [penSize, setPenSize] = useState(3);
  const [eraser, setEraser] = useState(false);
  const [strokes, setStrokes] = useState<Stroke[]>(diagram.strokes ?? []);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [showChoices, setShowChoices] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const current = useRef<Stroke | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => { setSpec(diagram); setStrokes(diagram.strokes ?? []); }, [diagram.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { closeButton.current?.focus(); }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const { placed, height, width: W, headers } = useMemo(() => layout(spec), [spec]);

  // Zoom to Fit: a big diagram is scaled to the room it has; Actual Size lets it scroll instead.
  const [fit, setFit] = useState(true);
  const [room, setRoom] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const element = stage.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (rect) setRoom({ w: rect.width, h: rect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const fitScale = room.w > 0 ? Math.min(1, room.w / W, spec.image ? 1 : Math.max(0.3, room.h / height)) : 1;
  const tooBig = fitScale < 0.97;
  const scale = fit ? fitScale : 1;
  const byId = useMemo(() => new Map(placed.map((n) => [n.id, n])), [placed]);
  const groupColor = (name: string) => {
    const index = spec.groups.findIndex((g) => g.label.toLowerCase() === (name || "").toLowerCase());
    return GROUP_COLORS[(index < 0 ? 0 : index) % GROUP_COLORS.length];
  };

  const save = useCallback(async (changes: Partial<Diagram>) => {
    const result = await api.put<{ diagram: Diagram }>(`/api/diagram/${spec.id}`, changes);
    if (result.ok) { setSpec(result.data.diagram); onChanged?.(result.data.diagram); }
    else setMessage(result.error);
  }, [spec.id, onChanged]);

  // --- drawing ------------------------------------------------------------------------------------
  const point = (event: React.PointerEvent): number[] => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box) return [0, 0];
    return [Math.round(((event.clientX - box.left) / box.width) * W), Math.round(((event.clientY - box.top) / box.height) * height)];
  };
  const startStroke = (event: React.PointerEvent) => {
    if (!drawing) return;
    (event.target as Element).setPointerCapture?.(event.pointerId);
    if (eraser) {
      const [x, y] = point(event);
      setStrokes((list) => list.filter((stroke) => !stroke.points.some(([px, py]) => Math.hypot(px - x, py - y) < 18)));
      return;
    }
    current.current = { color: penColor, size: penSize, points: [point(event)] };
    setStrokes((list) => [...list, current.current!]);
  };
  const moveStroke = (event: React.PointerEvent) => {
    if (!drawing || !current.current) return;
    current.current.points.push(point(event));
    setStrokes((list) => [...list.slice(0, -1), { ...current.current! }]);
  };
  const endStroke = () => {
    if (!current.current) return;
    current.current = null;
    void save({ strokes });
  };

  // --- export -------------------------------------------------------------------------------------
  const toPng = useCallback(async (): Promise<Blob | null> => {
    const svg = svgRef.current;
    if (!svg) return null;
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("width", String(W));
    clone.setAttribute("height", String(height));
    const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
    style.textContent = `text{font-family:-apple-system,Segoe UI,sans-serif}`;
    clone.insertBefore(style, clone.firstChild);
    const source = new XMLSerializer().serializeToString(clone);
    const url = URL.createObjectURL(new Blob([source], { type: "image/svg+xml;charset=utf-8" }));
    try {
      const image = new Image();
      image.decoding = "sync";
      await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
      const canvas = document.createElement("canvas");
      canvas.width = W * 2;
      canvas.height = height * 2;
      const ctx = canvas.getContext("2d");
      if (!ctx) return null;
      ctx.fillStyle = "#0b0b10";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      return await new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), "image/png"));
    } finally {
      URL.revokeObjectURL(url);
    }
  }, [height, W]);

  const savePng = async () => {
    setBusy("png");
    const blob = await toPng();
    setBusy("");
    if (!blob) { setMessage("The picture could not be made."); return; }
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${spec.title.replace(/[^\w -]+/g, "").slice(0, 40) || "diagram"}.png`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 8000);
  };

  const savePdf = async () => {
    // The browser's own print-to-PDF: no extra library, and it keeps the vectors sharp.
    setBusy("pdf");
    const blob = await toPng();
    setBusy("");
    if (!blob) { setMessage("The page could not be prepared."); return; }
    const url = URL.createObjectURL(blob);
    const frame = document.createElement("iframe");
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
    document.body.appendChild(frame);
    const doc = frame.contentDocument;
    if (!doc) { setMessage("The print view could not open."); return; }
    doc.write(`<html><head><title>${spec.title.replace(/[<>&]/g, "")}</title>
      <style>@page{size:landscape;margin:12mm}body{margin:0;font-family:system-ui,sans-serif;color:#111}
      h1{font-size:16pt;margin:0 0 6pt}p{font-size:10pt;color:#444;margin:0 0 10pt}img{width:100%}</style></head>
      <body><h1>${spec.title.replace(/[<>&]/g, "")}</h1><p>${(spec.caption || "").replace(/[<>&]/g, "")}</p>
      <img src="${url}" /></body></html>`);
    doc.close();
    const image = doc.querySelector("img");
    const go = () => { frame.contentWindow?.focus(); frame.contentWindow?.print(); window.setTimeout(() => { frame.remove(); URL.revokeObjectURL(url); }, 60_000); };
    if (image && !image.complete) image.onload = go; else go();
  };

  const putInChat = async () => {
    setBusy("chat");
    const blob = await toPng();
    if (!blob) { setBusy(""); setMessage("The picture could not be made."); return; }
    const response = await fetch("/api/uploads", {
      method: "POST", body: blob,
      headers: { "Content-Type": "image/png", "X-Filename": encodeURIComponent(`${spec.title.slice(0, 40) || "diagram"}.png`), ...authHeaders() },
    });
    setBusy("");
    if (!response.ok) { setMessage("Could not put it in the chat."); return; }
    const data = await response.json();
    const id = data?.upload?.id ?? data?.id;
    if (id) { onInsert?.(id, spec.title); setMessage("Added to the message box."); }
  };

  const pickImage = async (image: DiagramImage) => {
    setShowChoices(false);
    await save({ image });
  };

  const image = spec.image;
  const imageSrc = image ? (image.url.startsWith("http") && !image.url.startsWith(window.location.origin)
    ? `/api/image-proxy?url=${encodeURIComponent(image.url)}` : image.url) : "";

  return createPortal(
    <div className="dg-scrim" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`dg${tooBig ? " is-big" : ""}`} role="dialog" aria-modal="true" aria-labelledby="dg-title">
        <header className="dg__bar">
          <div className="dg__titles">
            <h2 id="dg-title">{spec.title}</h2>
            <p>
              {spec.source === "itself" ? "Drawn from this install" : spec.source === "offline" ? "Drawn without a model"
                : spec.source === "image" ? "Found on a free image library" : spec.source === "generated" ? "Drawn by the image model"
                : `${spec.helpers ?? 1} model pass${(spec.helpers ?? 1) > 1 ? "es" : ""}`}
              {spec.nodes.length > 1 ? ` · ${spec.nodes.length} boxes · ${spec.edges.length} links` : ""}
            </p>
          </div>
          <div className="dg__tools">
            <button className={`dg-btn${drawing ? " is-on" : ""}`} aria-pressed={drawing} onClick={() => setDrawing((v) => !v)}>
              {drawing ? "Drawing" : "Draw"}
            </button>
            {drawing && (
              <>
                <div className="dg-pens" role="group" aria-label="Pen colour">
                  {PEN_COLORS.map((colour) => (
                    <button key={colour} className={`dg-pen${penColor === colour && !eraser ? " is-on" : ""}`} style={{ background: colour }}
                      aria-label={`Pen ${colour}`} aria-pressed={penColor === colour && !eraser}
                      onClick={() => { setPenColor(colour); setEraser(false); }} />
                  ))}
                </div>
                <label className="dg-size">
                  <span className="sr-only">Pen size</span>
                  <input type="range" min={1} max={10} value={penSize} onChange={(e) => setPenSize(Number(e.target.value))} />
                </label>
                <button className={`dg-btn${eraser ? " is-on" : ""}`} aria-pressed={eraser} onClick={() => setEraser((v) => !v)}>Eraser</button>
                <button className="dg-btn" onClick={() => { setStrokes((list) => list.slice(0, -1)); void save({ strokes: strokes.slice(0, -1) }); }}
                  disabled={strokes.length === 0}>Undo</button>
                <button className="dg-btn" onClick={() => { setStrokes([]); void save({ strokes: [] }); }} disabled={strokes.length === 0}>Clear Ink</button>
              </>
            )}
            {tooBig && (
              <button className="dg-btn" onClick={() => setFit((v) => !v)} aria-pressed={!fit}>
                {fit ? "Actual Size" : "Zoom to Fit"}
              </button>
            )}
            <button className="dg-btn" onClick={() => void savePng()} disabled={Boolean(busy)}>{busy === "png" ? "Saving…" : "Save PNG"}</button>
            <button className="dg-btn" onClick={() => void savePdf()} disabled={Boolean(busy)}>{busy === "pdf" ? "Preparing…" : "Save PDF"}</button>
            {onInsert && <button className="dg-btn" onClick={() => void putInChat()} disabled={Boolean(busy)}>{busy === "chat" ? "Adding…" : "Put In Chat"}</button>}
            {(spec.image_choices?.length ?? 0) > 1 && (
              <button className="dg-btn" aria-expanded={showChoices} onClick={() => setShowChoices((v) => !v)}>Other Pictures</button>
            )}
            <button ref={closeButton} className="dg-btn dg-btn--close" onClick={onClose} aria-label="Close the diagram">✕</button>
          </div>
        </header>

        {showChoices && (spec.image_choices?.length ?? 0) > 0 && (
          <div className="dg-choices" role="listbox" aria-label="Other pictures">
            {spec.image_choices!.map((choice) => (
              <button key={choice.url} role="option" aria-selected={choice.url === image?.url} onClick={() => void pickImage(choice)}>
                <img src={`/api/image-proxy?url=${encodeURIComponent(choice.thumb || choice.url)}`} alt="" loading="lazy" />
                <span>{choice.title || choice.where}</span>
              </button>
            ))}
          </div>
        )}

        <div className="dg__stage" ref={stage}>
          {image && (
            <figure className="dg-photo">
              <img src={imageSrc} alt={image.title || spec.title} />
              <figcaption>
                {image.title || spec.title}
                {image.by ? ` · ${image.by}` : ""}{image.licence ? ` · ${image.licence}` : ""} · {image.where}
                {image.source && <> · <a href={image.source} target="_blank" rel="noopener noreferrer">source</a></>}
              </figcaption>
            </figure>
          )}
          <svg ref={svgRef} className={`dg-svg${drawing ? " is-drawing" : ""}`} viewBox={`0 0 ${W} ${height}`} role="img"
            style={{ width: Math.round(W * scale), height: Math.round(height * scale) }}
            aria-label={`${spec.title}. ${spec.caption || ""} ${spec.nodes.map((n) => n.label).join(", ")}`}
            onPointerDown={startStroke} onPointerMove={moveStroke} onPointerUp={endStroke} onPointerLeave={endStroke}>
            <defs>
              <marker id="dg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
              </marker>
            </defs>
            {spec.edges.map((edge, index) => {
              const from = byId.get(edge.from), to = byId.get(edge.to);
              if (!from || !to) return null;
              const colour = groupColor(from.group);
              const way = route(from, to, height);
              return (
                <g key={index} style={{ color: colour }}>
                  <path d={way.d} pathLength={edge.style === "dashed" ? undefined : 1}
                    className={`dg-edge is-${edge.style}${reduced ? "" : " is-live"}`} stroke={colour} markerEnd="url(#dg-arrow)" />
                  {edge.label && (
                    <text className="dg-edge__label" x={way.x} y={way.y} textAnchor={way.anchor}>{edge.label}</text>
                  )}
                </g>
              );
            })}
            {headers.map((header) => (
              <text key={header.label} x={header.x} y={22} className="dg-group-head" fill={groupColor(header.label)}>
                {header.label.toUpperCase()}
              </text>
            ))}
            {placed.map((node) => {
              const colour = groupColor(node.group);
              const label = node.label.length > LABEL_CHARS ? `${node.label.slice(0, LABEL_CHARS - 1)}…` : node.label;
              const lines = node.sub ? wrapSub(node.sub, SUB_CHARS) : [];
              const labelY = node.y + (lines.length === 2 ? 24 : lines.length === 1 ? 29 : 38);
              const radius = node.shape === "round" ? 26 : node.shape === "circle" ? NODE_H / 2 : node.shape === "note" ? 4 : 12;
              return (
                <g key={node.id} className="dg-node">
                  <title>{[node.label, node.group, node.sub].filter(Boolean).join(" — ")}</title>
                  <rect x={node.x} y={node.y} width={node.w} height={node.h} rx={radius} ry={radius}
                    fill="rgba(255,255,255,0.03)" stroke={colour} strokeWidth={1.4} />
                  <text x={node.x + 14} y={labelY} className="dg-node__label">{label}</text>
                  {lines.map((line, row) => (
                    <text key={row} x={node.x + 14} y={labelY + 17 + row * 15} className="dg-node__sub">{line}</text>
                  ))}
                </g>
              );
            })}
            {strokes.map((stroke, index) => (
              <polyline key={index} className="dg-ink" points={stroke.points.map(([x, y]) => `${x},${y}`).join(" ")}
                stroke={stroke.color} strokeWidth={stroke.size} />
            ))}
          </svg>
        </div>

        <footer className="dg__foot">
          {spec.caption && <p className="dg__caption">{spec.caption}</p>}
          {spec.notes.length > 0 && <ul className="dg__notes">{spec.notes.map((note, i) => <li key={i}>{note}</li>)}</ul>}
          {spec.groups.length > 0 && (
            <div className="dg__legend">
              {spec.groups.map((group) => (
                <span key={group.id}><i style={{ background: GROUP_COLORS[group.color % GROUP_COLORS.length] }} aria-hidden="true" />{group.label}</span>
              ))}
            </div>
          )}
          {message && <p className="dg__message" role="status">{message}</p>}
        </footer>
      </div>
    </div>,
    document.body,
  );
}
