/** "Local model warm 3:12" / "cold": Ollama unloads a model after 5 idle minutes, and the next answer waits for it to
 *  load again (doc 2 item 2.3, the mod's cache tax). Shown only once the local model has answered. Click to switch
 *  keep-warm on or off (a free local ping every 4 minutes). */

import { useEffect, useState } from "react";
import { api } from "../../api";

interface Warmth { ollama: { warm: boolean; seconds_left: number; used: boolean; model: string }; keep_warm: boolean }

export function CacheChip({ busy }: { busy: boolean }) {
  const [state, setState] = useState<Warmth | null>(null);
  const [left, setLeft] = useState(0);

  useEffect(() => {
    let alive = true;
    void api.get<Warmth>("/api/cache-warmth").then((r) => {
      if (alive && r.ok) { setState(r.data); setLeft(r.data.ollama.seconds_left); }
    });
    return () => { alive = false; };
  }, [busy]);
  useEffect(() => {
    if (left <= 0) return;
    const timer = window.setTimeout(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [left]);

  if (!state?.ollama.used && !state?.keep_warm) return null;
  const toggle = async () => {
    const r = await api.put<Warmth>("/api/cache-warmth", { keep_warm: !state.keep_warm });
    if (r.ok) { setState(r.data); setLeft(r.data.ollama.seconds_left); }
  };
  const warm = left > 0 || state.keep_warm;
  const clock = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  return (
    <button type="button" className={`cache-chip${warm ? " is-warm" : ""}`} onClick={() => void toggle()}
      title={`${state.ollama.model || "The local model"} stays loaded 5 minutes after it answers. `
        + (state.keep_warm ? "Keep-warm is on: click to turn it off." : "Click to keep it loaded while Ichos runs.")}>
      <span className="cache-chip__dot" aria-hidden="true" />
      {state.keep_warm ? "Local model kept warm" : warm ? `Local model warm ${clock}` : "Local model cold"}
    </button>
  );
}
