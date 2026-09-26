/** "Nyx is turned off" — one button to turn it on.
 *
 * Shown whenever the page is open but the engine is not answering: after a
 * reboot with the tab restored, after "Turn off Nyx", or if the engine crashed.
 * The old version was a small badge reading "Backend offline — Start" plus a
 * shell command to copy into a terminal; the owner's instruction was that nobody
 * should ever have to copy and paste anything to use Nyx.
 *
 * The button follows the nyx:// link setup registered, then this screen watches
 * the engine and gets out of the way by itself the moment it answers.
 */

import { useEffect, useRef, useState } from "react";
import { NyxAvatar } from "./NyxAvatar";
import { requestEngineStart, waitForEngine } from "../engine";

type Phase = "off" | "starting" | "slow" | "on";

/** How long the start button waits before explaining what else to try. */
const HELP_AFTER_SECONDS = 9;
/** How long one attempt keeps watching for the engine. */
const ATTEMPT_MS = 90_000;

export function EngineGate({ onOnline, stopped }: {
  onOnline: () => void;
  /** True when the owner turned Nyx off from Settings, so the wording fits. */
  stopped?: boolean;
}) {
  const [phase, setPhase] = useState<Phase>("off");
  const [elapsed, setElapsed] = useState(0);
  const cancelled = useRef(false);

  // Keep watching quietly even before a click: start-with-Windows or a desktop
  // shortcut may bring the engine up while this screen is showing.
  useEffect(() => {
    cancelled.current = false;
    let alive = true;
    void (async () => {
      while (alive) {
        const up = await waitForEngine(4000, undefined, () => !alive);
        if (up && alive) {
          setPhase("on");
          window.setTimeout(onOnline, 450);
          return;
        }
      }
    })();
    return () => {
      alive = false;
      cancelled.current = true;
    };
  }, [onOnline]);

  async function turnOn(force = false) {
    if (!force && (phase === "starting" || phase === "slow")) return;
    setPhase("starting");
    setElapsed(0);
    requestEngineStart("start");
    const up = await waitForEngine(
      ATTEMPT_MS,
      (seconds) => {
        setElapsed(seconds);
        if (seconds >= HELP_AFTER_SECONDS) setPhase((p) => (p === "starting" ? "slow" : p));
      },
      () => cancelled.current,
    );
    if (cancelled.current) return;
    if (up) {
      setPhase("on");
      window.setTimeout(onOnline, 450);
    } else {
      setPhase("slow");
    }
  }

  const busy = phase === "starting" || phase === "slow";

  return (
    <div className="engine-gate" role="dialog" aria-modal="true" aria-labelledby="engine-gate-title">
      <div className="engine-gate__glow" aria-hidden="true" />
      <div className="engine-gate__card">
        <div className={`engine-gate__avatar ${busy ? "is-busy" : ""} ${phase === "on" ? "is-on" : ""}`}>
          <NyxAvatar state={phase === "on" ? "idle" : busy ? "thinking" : "idle"} size={96} />
        </div>

        <h1 id="engine-gate-title" className="engine-gate__title">
          {phase === "on" ? "Nyx is on" : stopped ? "Nyx is turned off" : "Nyx is turned off"}
        </h1>
        <p className="engine-gate__lead">
          {phase === "on"
            ? "Reconnecting…"
            : busy
              ? `Starting Nyx on this computer… ${elapsed > 0 ? `${elapsed}s` : ""}`
              : "Nyx runs on this computer. Turn it on and this page reconnects by itself."}
        </p>

        {phase !== "on" && (
          <button
            className="engine-gate__button"
            onClick={() => void turnOn()}
            disabled={busy}
            autoFocus
          >
            {busy ? <span className="engine-gate__spinner" aria-hidden="true" /> : null}
            {busy ? "Starting…" : "Turn on Nyx"}
          </button>
        )}

        {busy && <div className="nyx-progress engine-gate__progress"><span /></div>}

        {phase === "slow" && (
          <div className="engine-gate__help" aria-live="polite">
            <strong>Still starting?</strong>
            <ul>
              <li>
                Your browser may be asking whether to open <em>Nyx Ichos</em> — choose <b>Open</b>
                {" "}(and tick “always allow” so it never asks again).
              </li>
              <li>
                Or double-click <b>Nyx Ichos</b> on your desktop.
              </li>
              <li>
                Not set up on this computer yet? Double-click <b>Start Nyx</b> in the Nyx folder once.
              </li>
            </ul>
            <button className="btn btn-secondary" onClick={() => void turnOn(true)}>
              Try again
            </button>
          </div>
        )}

        {phase === "off" && (
          <div className="engine-gate__foot">
            First time? Your browser may ask to open Nyx — choose Open.
          </div>
        )}
      </div>
    </div>
  );
}
