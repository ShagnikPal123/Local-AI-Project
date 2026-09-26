/** "Nyx is using your mouse" — visible whenever computer control is acting, with Stop.
 *
 * Fed by `computer.action` / `computer.state` on the workspace bus, so it shows in
 * every open window, whichever tab is active. The desktop overlay shows the AI
 * cursor on the screen itself; this is the in-app half, and the Stop button
 * (like Esc×3 or slamming the mouse into a top-left corner) aborts the sequence.
 */

import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { onWorkspaceEvent } from "../state/workspaceEvents";

type Banner = { kind: "acting"; label: string; count: number } | { kind: "stopped"; label: string };

export function ComputerBanner() {
  const [banner, setBanner] = useState<Banner | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => onWorkspaceEvent((event) => {
    const e = event as { type: string; label?: string; stopped?: string };
    if (e.type === "computer.action") {
      setBanner((current) => ({ kind: "acting", label: e.label ?? "Working", count: current?.kind === "acting" ? current.count + 1 : 1 }));
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setBanner(null), 8000);
    } else if (e.type === "computer.state" && e.stopped) {
      setBanner({ kind: "stopped", label: e.stopped });
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setBanner(null), 5000);
    }
  }), []);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  if (!banner) return null;
  return (
    <div className={`computer-banner ${banner.kind === "stopped" ? "is-stopped" : ""}`} role="status" aria-live="polite">
      <span className="computer-banner__dot" aria-hidden="true" />
      {banner.kind === "acting" ? (
        <>
          <span><strong>Nyx is using your mouse and keyboard</strong> · {banner.label}</span>
          <span className="computer-banner__hint">Esc ×3 or top-left corner also stops</span>
          <button className="btn btn-primary btn-sm" type="button" onClick={() => void api.post("/api/computer/stop")}>Stop</button>
        </>
      ) : (
        <span><strong>Computer control stopped</strong> · {banner.label}</span>
      )}
    </div>
  );
}
