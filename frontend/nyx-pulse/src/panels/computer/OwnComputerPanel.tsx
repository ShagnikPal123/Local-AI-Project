/** Nyx's Computer (Update 1, U49): a desktop of its own, so it never has to borrow yours.
 *
 * The owner: "it will basically have its own computer setup so when I don't want it to use my screen it works on
 * this one and won't interrupt me unless I say it can or it asks." So this tab is three things:
 *
 *  • **Where Nyx works** — its own computer only, ask before using your screen (the default), or your screen too.
 *    A yes to "may I use your screen?" lasts a few minutes and can be taken back here.
 *  • **Setting it up** — Cua's sandbox runs in Docker on this PC (free) or in Cua Cloud (your account, billed by
 *    Cua). Each step says exactly what is missing; only the part Nyx can do itself has a button.
 *  • **Watching it** — the live screen, what it did, and your own turn on it: click the picture, type, press keys.
 */

import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { api, authHeaders } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import "./computer.css";

type ScreenMode = "never" | "ask" | "allow";

interface Status {
  settings: { my_screen: ScreenMode; provider: "docker" | "cloud"; image: string; cloud_name: string; grant_minutes: number };
  sdk: boolean;
  docker: "" | "missing" | "stopped" | "ready";
  cloud_key: boolean;
  ready: boolean;
  next: string;
  link: string;
  computer: { state: "off" | "starting" | "on" | "error" | "stopping"; error: string; started_at: number;
    actions: { ts: number; kind: string; text: string }[] };
  grant: { active: boolean; seconds_left: number };
}

const MODES: { id: ScreenMode; name: string; means: string }[] = [
  { id: "never", name: "Its own computer only", means: "Nyx never touches your screen, mouse or keyboard." },
  { id: "ask", name: "Ask before my screen", means: "It works on its own computer and asks you first if a job needs your screen." },
  { id: "allow", name: "My screen too", means: "It may use your screen without asking, as before." },
];

function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

export function OwnComputerPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [shot, setShot] = useState("");
  const [typed, setTyped] = useState("");
  const [key, setKey] = useState("");
  const [cloudName, setCloudName] = useState("");
  const img = useRef<HTMLImageElement>(null);

  const load = useCallback(async () => {
    const result = await api.get<Status>("/api/own-computer");
    if (result.ok) { setStatus(result.data); setCloudName((n) => n || result.data.settings.cloud_name); }
    else setError(result.error);
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => onWorkspaceEvent((event) => {
    if (event.type === "own_computer.action") void load();
  }), [load]);

  const on = status?.computer.state === "on";

  // The live view: a fresh picture every 1.5 s while it is on and this tab is visible.
  useEffect(() => {
    if (!on) { setShot(""); return; }
    let alive = true;
    let url = "";
    const grab = async () => {
      if (document.hidden) return;
      try {
        const response = await fetch("/api/own-computer/screen", { headers: authHeaders() });
        if (!response.ok || !alive) return;
        const next = URL.createObjectURL(await response.blob());
        if (url) URL.revokeObjectURL(url);
        url = next;
        setShot(next);
      } catch { /* the next tick tries again */ }
    };
    void grab();
    const timer = window.setInterval(() => void grab(), 1500);
    return () => { alive = false; window.clearInterval(timer); if (url) URL.revokeObjectURL(url); };
  }, [on]);

  const call = async (label: string, path: string, body: unknown = {}) => {
    setBusy(label);
    setError("");
    const result = await api.post<Status>(path, body, 600_000);
    setBusy("");
    if (result.ok && result.data && "settings" in (result.data as object)) setStatus(result.data);
    else if (!result.ok) setError(result.error);
    else void load();
  };

  const act = async (body: Record<string, unknown>) => {
    const result = await api.post<{ done: string }>("/api/own-computer/act", body);
    if (!result.ok) setError(result.error);
  };

  const clickShot = (event: MouseEvent<HTMLImageElement>) => {
    const box = img.current;
    if (!box || !box.naturalWidth) return;
    const rect = box.getBoundingClientRect();
    const x = Math.round(((event.clientX - rect.left) / rect.width) * box.naturalWidth);
    const y = Math.round(((event.clientY - rect.top) / rect.height) * box.naturalHeight);
    void act({ kind: "click", x, y, double: event.detail === 2 });
  };

  if (!status) {
    return <div className="ocp"><p className="ocp-muted">{error || "Loading Nyx's computer…"}</p></div>;
  }
  const s = status.settings;
  const state = status.computer.state;

  return (
    <div className="ocp">
      <header className="ocp-head">
        <div>
          <h1>Nyx's Computer</h1>
          <p className="ocp-muted">A desktop of its own, so it does not have to use yours.</p>
        </div>
        <span className={`ocp-pill is-${state}`}><i />{{ off: "Off", starting: "Starting…", on: "On", error: "Could not start", stopping: "Stopping…" }[state]}</span>
      </header>

      {error && <p className="ocp-error" role="alert">{error}</p>}

      <section className="ocp-card" aria-labelledby="ocp-where">
        <h2 id="ocp-where">Where Nyx works</h2>
        <div className="ocp-modes" role="radiogroup" aria-labelledby="ocp-where">
          {MODES.map((mode) => (
            <button key={mode.id} type="button" role="radio" aria-checked={s.my_screen === mode.id}
                    className={`ocp-mode${s.my_screen === mode.id ? " is-on" : ""}`}
                    onClick={() => void call("mode", "/api/own-computer/settings", { my_screen: mode.id })}>
              <b>{mode.name}</b>
              <span>{mode.means}</span>
            </button>
          ))}
        </div>
        {status.grant.active && (
          <p className="ocp-grant">
            You let Nyx use your screen — {Math.ceil(status.grant.seconds_left / 60)} min left.
            <button type="button" className="ocp-link" onClick={() => void call("revoke", "/api/own-computer/grant/revoke")}>Take it back</button>
          </p>
        )}
      </section>

      <section className="ocp-card" aria-labelledby="ocp-setup">
        <h2 id="ocp-setup">Its computer</h2>
        <div className="segmented ocp-provider" role="group" aria-label="Where its computer runs">
          <button type="button" aria-pressed={s.provider === "docker"} disabled={on}
                  onClick={() => void call("provider", "/api/own-computer/settings", { provider: "docker" })}>On this PC (Docker)</button>
          <button type="button" aria-pressed={s.provider === "cloud"} disabled={on}
                  onClick={() => void call("provider", "/api/own-computer/settings", { provider: "cloud" })}>Cua Cloud</button>
        </div>
        <ol className="ocp-steps">
          <li className={status.sdk ? "is-done" : ""}>
            <b>Cua Computer SDK</b>
            {status.sdk ? <span>Installed</span> : (
              <button type="button" className="btn btn-secondary" disabled={!!busy}
                      onClick={() => void call("setup", "/api/own-computer/setup")}>{busy === "setup" ? "Installing…" : "Set up"}</button>
            )}
          </li>
          {s.provider === "docker" ? (
            <li className={status.docker === "ready" ? "is-done" : ""}>
              <b>Docker Desktop</b>
              {status.docker === "ready" ? <span>Running</span>
                : status.docker === "stopped" ? <span>Installed — open Docker Desktop so it is running</span>
                  : <span>Not installed. It is free; it sets up WSL 2 and needs a restart. <a href="https://www.docker.com/products/docker-desktop/" target="_blank" rel="noopener noreferrer">Get Docker Desktop ↗</a></span>}
            </li>
          ) : (
            <>
              <li className={status.cloud_key ? "is-done" : ""}>
                <b>Cua Cloud key</b>
                {status.cloud_key ? (
                  <span>Saved <button type="button" className="ocp-link" onClick={() => void call("key", "/api/own-computer/key", { key: "" })}>Remove</button></span>
                ) : (
                  <form className="ocp-inline" onSubmit={(e) => { e.preventDefault(); void call("key", "/api/own-computer/key", { key }); setKey(""); }}>
                    <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Paste your Cua API key"
                           aria-label="Cua Cloud API key" autoComplete="off" />
                    <button className="btn btn-secondary" disabled={!key.trim()}>Save</button>
                  </form>
                )}
                <span className="ocp-muted">From <a href="https://cua.ai" target="_blank" rel="noopener noreferrer">cua.ai ↗</a>. Cua bills cloud sandboxes by usage.</span>
              </li>
              <li className={s.cloud_name ? "is-done" : ""}>
                <b>Sandbox name</b>
                <form className="ocp-inline" onSubmit={(e) => { e.preventDefault(); void call("name", "/api/own-computer/settings", { cloud_name: cloudName.trim() }); }}>
                  <input value={cloudName} onChange={(e) => setCloudName(e.target.value)} placeholder="The sandbox you made on cua.ai"
                         aria-label="Cua Cloud sandbox name" />
                  <button className="btn btn-secondary" disabled={!cloudName.trim() || cloudName.trim() === s.cloud_name}>Save</button>
                </form>
              </li>
            </>
          )}
        </ol>
        {!status.ready && <p className="ocp-next"><b>Next:</b> {status.next}</p>}
        <div className="ocp-row">
          {state === "on" || state === "stopping" ? (
            <button type="button" className="btn btn-secondary" disabled={!!busy || state === "stopping"}
                    onClick={() => void call("stop", "/api/own-computer/stop")}>{busy === "stop" ? "Stopping…" : "Turn it off"}</button>
          ) : (
            <button type="button" className="btn btn-primary" disabled={!status.ready || !!busy}
                    onClick={() => void call("start", "/api/own-computer/start")}>
              {busy === "start" ? "Starting — the first time downloads its desktop…" : "Start Nyx's computer"}
            </button>
          )}
          <button type="button" className="btn btn-plain" disabled={!!busy} onClick={() => void load()}>Check again</button>
        </div>
        {status.computer.error && state === "error" && <p className="ocp-error">{status.computer.error}</p>}
      </section>

      {on && (
        <section className="ocp-card ocp-live" aria-labelledby="ocp-live">
          <h2 id="ocp-live">Live <span className="ocp-muted">— click the picture to click on its computer</span></h2>
          {shot ? <img ref={img} src={shot} alt="Nyx's computer screen, live" onClick={clickShot} className="ocp-screen" />
            : <p className="ocp-muted">Waiting for the first picture…</p>}
          <form className="ocp-inline" onSubmit={(e) => { e.preventDefault(); if (typed) { void act({ kind: "type", text: typed }); setTyped(""); } }}>
            <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type on its computer" aria-label="Type on Nyx's computer" />
            <button className="btn btn-secondary" disabled={!typed}>Type</button>
            <button type="button" className="btn btn-plain" onClick={() => void act({ kind: "keys", text: "enter" })}>Enter</button>
            <button type="button" className="btn btn-plain" onClick={() => void act({ kind: "scroll", amount: -3 })}>Scroll down</button>
          </form>
        </section>
      )}

      {status.computer.actions.length > 0 && (
        <section className="ocp-card" aria-labelledby="ocp-did">
          <h2 id="ocp-did">What it did</h2>
          <ol className="ocp-actions">
            {[...status.computer.actions].reverse().map((action, index) => (
              <li key={`${action.ts}-${index}`}><time>{clock(action.ts)}</time><span>{action.text}</span></li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
