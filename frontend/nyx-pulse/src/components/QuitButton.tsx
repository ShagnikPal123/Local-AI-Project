/** Log Out: sign out and stop Nyx running in the background (Request H17).
 *
 * "Add a log out button so that it shuts off the app running in background. As you move your mouse
 * onto the rectangular button, blue fills in the box. Then in the middle of the screen have a
 * confirmation with similar aspects, not the same but similar appeal."
 *
 * The bar button fills left-to-right on hover. The confirmation echoes it without copying it: its
 * top band fills once as it opens, and its primary button fills bottom-to-top. Cancel is the default
 * (Escape and Return on Cancel), because quitting is consequential even though nothing is lost.
 */

import { useEffect, useRef, useState } from "react";
import { api, setToken } from "../api";

type Phase = "idle" | "confirm" | "quitting" | "stopped";

function PowerGlyph({ size = 16 }: { size?: number }) {
  return (
    <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
      <path d="M10 2.5v7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M5.6 5.2a6.5 6.5 0 1 0 8.8 0" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function QuitButton({ signedIn }: { signedIn: boolean }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const cancelRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (phase !== "confirm") return;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setPhase("idle"); openerRef.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase]);

  async function quit() {
    setPhase("quitting");
    setError("");
    const stopped = await api.post<{ ok: boolean }>("/api/engine/stop", {});
    if (!stopped.ok) {
      setError(stopped.status === 409
        ? "This copy of Nyx was started by hand, so it has to be stopped where it was started."
        : stopped.error);
      setPhase("confirm");
      return;
    }
    if (signedIn) {
      try { await api.post("/api/auth/logout", {}); } catch { /* the engine may already be gone */ }
    }
    setToken(null);
    setPhase("stopped");
  }

  return (
    <>
      <button ref={openerRef} className="quit-btn" onClick={() => setPhase("confirm")} aria-haspopup="dialog"
        aria-label="Log out and quit Nyx" title="Log out and stop Nyx running in the background">
        <span className="quit-btn__fill" aria-hidden="true" />
        <span className="quit-btn__label"><PowerGlyph size={14} />Log Out</span>
      </button>

      {(phase === "confirm" || phase === "quitting") && (
        <div className="quit-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget && phase === "confirm") setPhase("idle"); }}>
          <div className="quit-dialog" role="alertdialog" aria-modal="true" aria-labelledby="quit-title" aria-describedby="quit-body">
            <div className="quit-dialog__band" aria-hidden="true" />
            <div className="quit-dialog__icon" aria-hidden="true"><PowerGlyph size={26} /></div>
            <h2 id="quit-title">Log out and quit Nyx?</h2>
            <p id="quit-body">
              Nyx stops running in the background on this PC{signedIn ? " and signs you out" : ""}. Your chats, notes and
              settings are saved. Open Nyx from the Start menu or its shortcut to come back.
            </p>
            {error && <p className="quit-dialog__error" role="alert">{error}</p>}
            <div className="quit-dialog__actions">
              <button ref={cancelRef} className="btn btn-secondary quit-dialog__cancel" disabled={phase === "quitting"}
                onClick={() => { setPhase("idle"); openerRef.current?.focus(); }}>
                Cancel
              </button>
              <button className="quit-confirm" disabled={phase === "quitting"} onClick={() => void quit()}>
                <span className="quit-confirm__fill" aria-hidden="true" />
                <span className="quit-confirm__label">{phase === "quitting" ? "Quitting…" : "Log Out & Quit"}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {phase === "stopped" && (
        <div className="quit-scrim quit-scrim--solid" role="status" aria-live="polite">
          <div className="quit-dialog quit-dialog--done">
            <div className="quit-dialog__band is-full" aria-hidden="true" />
            <div className="quit-dialog__icon" aria-hidden="true"><PowerGlyph size={26} /></div>
            <h2>Nyx has stopped</h2>
            <p>It is no longer running in the background. You can close this window.</p>
          </div>
        </div>
      )}
    </>
  );
}
