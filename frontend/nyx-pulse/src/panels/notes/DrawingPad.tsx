/** Draw, then have Nyx read the sketch into notes (Request G13).
 *
 * A sheet over the editor: pen, highlighter and eraser, a few colours, undo,
 * and dark or paper background. Pointer pressure changes the line width on pens
 * and tablets. "Read into Notes" uploads the picture and the image model turns
 * handwriting, equations and diagrams into Markdown.
 */

import { useEffect, useRef, useState } from "react";

type Tool = "pen" | "highlighter" | "eraser";
interface Stroke { tool: Tool; color: string; size: number; points: [number, number, number][] }

const COLORS = ["#f5f5f7", "#64d2ff", "#ff6b6b", "#30d158", "#ffd60a", "#bf5af2"];

export function DrawingPad({ onClose, onRead, onSaveOnly, busy }: {
  onClose: () => void;
  onRead: (png: Blob, hint: string) => void;
  onSaveOnly: (png: Blob) => void;
  busy: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [tool, setTool] = useState<Tool>("pen");
  const [color, setColor] = useState(COLORS[0]);
  const [size, setSize] = useState(3);
  const [paper, setPaper] = useState(false);
  const [strokes, setStrokes] = useState<Stroke[]>([]);
  const [hint, setHint] = useState("");
  const current = useRef<Stroke | null>(null);

  const ink = (c: string) => (paper && c === "#f5f5f7" ? "#1d1d1f" : c);

  function redraw(list: Stroke[]) {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const ratio = window.devicePixelRatio || 1;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.fillStyle = paper ? "#fbfbf8" : "#0e0e13";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    for (const stroke of list) {
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.globalAlpha = stroke.tool === "highlighter" ? 0.35 : 1;
      ctx.strokeStyle = stroke.tool === "eraser" ? (paper ? "#fbfbf8" : "#0e0e13") : ink(stroke.color);
      for (let i = 1; i < stroke.points.length; i += 1) {
        const [x0, y0] = stroke.points[i - 1];
        const [x1, y1, p] = stroke.points[i];
        ctx.lineWidth = stroke.size * (stroke.tool === "highlighter" ? 5 : stroke.tool === "eraser" ? 6 : 0.6 + p * 0.9);
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(canvas.clientWidth * ratio);
      canvas.height = Math.round(canvas.clientHeight * ratio);
      redraw(strokes);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paper]);

  useEffect(() => { redraw(strokes); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [strokes, paper]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); setStrokes((s) => s.slice(0, -1)); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const point = (e: React.PointerEvent<HTMLCanvasElement>): [number, number, number] => {
    const rect = e.currentTarget.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top, e.pressure > 0 && e.pointerType !== "mouse" ? e.pressure : 0.5];
  };

  function exportPng(done: (blob: Blob) => void) {
    canvasRef.current?.toBlob((blob) => { if (blob) done(blob); }, "image/png");
  }

  return (
    <div className="notes-draw" role="dialog" aria-modal="true" aria-label="Drawing pad">
      <div className="notes-draw__bar">
        <div className="segmented" role="group" aria-label="Tool">
          {(["pen", "highlighter", "eraser"] as Tool[]).map((t) => (
            <button key={t} aria-pressed={tool === t} onClick={() => setTool(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
          ))}
        </div>
        <div className="notes-draw__colors" role="group" aria-label="Colour">
          {COLORS.map((c) => (
            <button key={c} className="notes-draw__swatch" style={{ background: ink(c) }} aria-pressed={color === c}
              aria-label={`Colour ${c}`} onClick={() => { setColor(c); if (tool === "eraser") setTool("pen"); }} />
          ))}
        </div>
        <label className="notes-draw__size">
          <span>Size</span>
          <input type="range" className="slider" min={1} max={10} value={size} onChange={(e) => setSize(Number(e.target.value))}
            style={{ ["--fill" as string]: `${((size - 1) / 9) * 100}%` }} />
        </label>
        <button className="btn btn-secondary" onClick={() => setPaper((v) => !v)} aria-pressed={paper}>{paper ? "Dark" : "Paper"}</button>
        <button className="btn btn-secondary" onClick={() => setStrokes((s) => s.slice(0, -1))} disabled={!strokes.length}>Undo</button>
        <button className="btn btn-secondary" onClick={() => setStrokes([])} disabled={!strokes.length}>Clear</button>
        <button className="btn btn-secondary notes-draw__close" onClick={onClose}>Close</button>
      </div>
      <canvas
        ref={canvasRef}
        className="notes-draw__canvas"
        aria-label="Drawing surface"
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          current.current = { tool, color, size, points: [point(e)] };
        }}
        onPointerMove={(e) => {
          if (!current.current) return;
          current.current.points.push(point(e));
          redraw([...strokes, current.current]);
        }}
        onPointerUp={() => {
          if (current.current && current.current.points.length > 0) setStrokes((s) => [...s, current.current as Stroke]);
          current.current = null;
        }}
      />
      <div className="notes-draw__foot">
        <input value={hint} onChange={(e) => setHint(e.target.value)} placeholder="Optional: what is this? e.g. Krebs cycle diagram"
          aria-label="What the drawing shows" />
        <button className="btn btn-secondary" disabled={!strokes.length || busy} onClick={() => exportPng(onSaveOnly)}>Add Sketch Only</button>
        <button className="btn btn-primary" disabled={!strokes.length || busy} onClick={() => exportPng((png) => onRead(png, hint))}>
          {busy ? "Reading…" : "Read into Notes"}
        </button>
      </div>
    </div>
  );
}
