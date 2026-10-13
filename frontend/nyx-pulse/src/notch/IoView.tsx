/** React wrapper around the Io canvas engine, plus the pointer feed it looks at. */

import { useEffect, useRef } from "react";
import { Io, type IoEmote, type IoState } from "./io";

type PointerListener = (x: number, y: number) => void;
const listeners = new Set<PointerListener>();
let last = { x: -1, y: -1 };

function emit(x: number, y: number) {
  last = { x, y };
  listeners.forEach((fn) => fn(x, y));
}

if (typeof window !== "undefined") {
  window.addEventListener("mousemove", (e) => emit(e.clientX, e.clientY), { passive: true });
  // The desktop window is click-through most of the time, so the host (notch_window.py) feeds the cursor in.
  (window as unknown as { __notchCursor?: PointerListener }).__notchCursor = emit;
}

export function onPointer(fn: PointerListener): () => void {
  listeners.add(fn);
  if (last.x >= 0) fn(last.x, last.y);
  return () => listeners.delete(fn);
}

export interface IoViewProps {
  /** Body width in CSS px (the canvas is larger so hands, badge and particles fit). */
  size: number;
  state?: IoState;
  emote?: { name: IoEmote; at: number } | null;
  tint?: string;
  details?: boolean;
  image?: string;
  levels?: () => number[];
  mic?: () => number;
  className?: string;
  title?: string;
  onClick?: (e: React.MouseEvent) => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
  onMouseDown?: (e: React.MouseEvent) => void;
}

export function IoView(props: IoViewProps) {
  const { size, state = "idle", emote, tint = "", details = true, image = "" } = props;
  const canvas = useRef<HTMLCanvasElement>(null);
  const holder = useRef<HTMLSpanElement>(null);
  const io = useRef<Io | null>(null);
  const side = Math.round(size / 0.6);

  useEffect(() => {
    if (!canvas.current) return;
    const engine = new Io(canvas.current, side, { tint, details, levels: props.levels, mic: props.mic });
    io.current = engine;
    engine.start();
    const off = onPointer((x, y) => {
      const box = holder.current?.getBoundingClientRect();
      if (box) engine.lookAt(x - (box.left + box.width / 2), y - (box.top + box.height / 2));
    });
    return () => {
      off();
      engine.destroy();
      io.current = null;
    };
    // The engine lives as long as the element; props below are pushed into it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => io.current?.resize(side), [side]);
  useEffect(() => io.current?.setState(state), [state]);
  useEffect(() => {
    if (io.current) io.current.opts = { ...io.current.opts, tint, details, levels: props.levels, mic: props.mic };
  }, [tint, details, props.levels, props.mic]);
  useEffect(() => {
    if (emote?.name) io.current?.setEmote(emote.name);
  }, [emote?.at, emote?.name]);
  useEffect(() => {
    if (!image) {
      if (io.current) io.current.opts.image = null;
      return;
    }
    const img = new Image();
    img.onload = () => {
      if (io.current) io.current.opts.image = img;
    };
    img.src = image;
  }, [image]);

  return (
    <span
      ref={holder}
      className={`nx-io ${props.className ?? ""}`}
      style={{ width: size, height: size }}
      title={props.title}
      onClick={(e) => {
        io.current?.poke();
        props.onClick?.(e);
      }}
      onContextMenu={props.onContextMenu}
      onMouseEnter={props.onMouseEnter}
      onMouseLeave={props.onMouseLeave}
      onMouseDown={props.onMouseDown}
    >
      <canvas ref={canvas} />
    </span>
  );
}

/** A mini Io standing for another agent, tinted with its colour. */
export function MiniIo({ color, size = 13, state = "idle" }: { color: string; size?: number; state?: IoState }) {
  return (
    <span className="nx-mini" style={{ width: size, height: size }}>
      <IoView size={size} tint={color} state={state} details={size > 18} />
    </span>
  );
}
