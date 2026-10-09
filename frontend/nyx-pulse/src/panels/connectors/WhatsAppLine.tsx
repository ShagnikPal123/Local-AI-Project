/** The WhatsApp line (whatsapp_link.py): text Nyx from your phone, and let Nyx text you.
 *
 * The owner: "I give it a number and it establishes a connection line where the user puts in their phone … all I
 * have to do is confirm as it used … something unique to the PC so it always communicates to the correct
 * phone/PC." So the card walks through exactly that: set up once, type your number, confirm the code on the phone,
 * and from then on it says which PC the line is tied to.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";

interface LogEntry { at: string; dir: "in" | "out"; text: string }

interface Line {
  installed: boolean;
  status: "unpaired" | "pairing" | "linked" | "moved";
  connected: boolean;
  pair_code: string;
  phone: string;
  mode: "self" | "number";
  nyx_number: string;
  pc: string;
  this_pc: string;
  paired_at: string;
  enabled: boolean;
  allow: "chat" | "full";
  log: LogEntry[];
  error: string;
}

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function WhatsAppLine() {
  const [line, setLine] = useState<Line | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [phone, setPhone] = useState("");
  const [mode, setMode] = useState<"self" | "number">("self");
  const [nyxNumber, setNyxNumber] = useState("");
  const [text, setText] = useState("");
  const [sent, setSent] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<Line>("/api/whatsapp");
    if (result.ok) setLine(result.data);
    else if (result.status !== 404) setError(result.error);
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const every = line?.status === "pairing" ? 2000 : 10000;
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, every);
    return () => window.clearInterval(timer);
  }, [line?.status, load]);

  const call = async (name: string, path: string, body?: unknown, timeout?: number) => {
    setBusy(name);
    setError("");
    const result = await api.post<Line>(path, body, timeout);
    setBusy("");
    if (!result.ok) { setError(result.error); return false; }
    if (result.data && "status" in (result.data as object)) setLine(result.data);
    else await load();
    return true;
  };

  if (!line) return error ? <p className="cx-muted">WhatsApp: {error}</p> : null;

  const linked = line.status === "linked";
  const head = (
    <div className="wa-head">
      <span className="wa-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20"><path fill="currentColor" d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2Zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2Zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8s-.4-.1-.6.1-.7.8-.8 1-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.3-.4.2-.4.7-1.3.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.7 11.8 11.8 0 0 0 4.5 4c1.7.7 2.3.8 3.2.6a2.7 2.7 0 0 0 1.8-1.2 2.2 2.2 0 0 0 .1-1.3c0-.1-.2-.2-.5-.3Z"/></svg>
      </span>
      <div>
        <h2 className="cx-group__title">Text Nyx from your phone
          <span>{linked ? (line.connected ? "connected" : "") : ""}</span>
        </h2>
        <p className="cx-muted">
          {linked
            ? <>WhatsApp {line.phone} ↔ <b>{line.pc}</b>{line.connected ? "" : " · not connected right now"}{line.enabled ? "" : " · paused"}</>
            : "Over WhatsApp, tied to this PC. Text it anything; it can text you back when a job is done."}
        </p>
      </div>
    </div>
  );

  return (
    <section className="wa" aria-label="WhatsApp">
      {head}
      {error && <p className="wa-error" role="alert">{error}</p>}
      {line.error && !error && <p className="wa-error" role="status">{line.error}</p>}

      {!line.installed && (
        <div className="wa-row">
          <p className="cx-muted">One download (about 7 MB): the WhatsApp client Nyx uses to link this PC as one of your devices.</p>
          <button className="btn btn-primary" disabled={!!busy} onClick={() => void call("setup", "/api/whatsapp/setup", undefined, 900000)}>
            {busy === "setup" ? "Setting up…" : "Set Up WhatsApp"}
          </button>
        </div>
      )}

      {line.installed && (line.status === "unpaired" || line.status === "moved") && (
        <form className="wa-form" onSubmit={(event) => { event.preventDefault(); void call("pair", "/api/whatsapp/pair", { phone, mode, nyx_number: nyxNumber }, 90000); }}>
          {line.status === "moved" && (
            <p className="wa-error">This line was made on {line.pc || "another PC"}. Pair again to use it on {line.this_pc}.</p>
          )}
          <label className="cx-field"><span>Your phone number <em>with the country code</em></span>
            <input className="cx-search" inputMode="tel" autoComplete="tel" placeholder="+44 7700 900123" value={phone}
              onChange={(event) => setPhone(event.target.value)} required />
          </label>
          <fieldset className="wa-choice">
            <legend className="cx-muted">Which WhatsApp does Nyx use?</legend>
            <label className={mode === "self" ? "is-on" : ""}>
              <input type="radio" name="wa-mode" checked={mode === "self"} onChange={() => setMode("self")} />
              <span><b>My own WhatsApp</b><span className="cx-muted">You talk to Nyx in your “Message yourself” chat. Nyx only reads that one chat — nothing else.</span></span>
            </label>
            <label className={mode === "number" ? "is-on" : ""}>
              <input type="radio" name="wa-mode" checked={mode === "number"} onChange={() => setMode("number")} />
              <span><b>A separate number for Nyx</b><span className="cx-muted">A spare SIM or eSIM with WhatsApp on it. You text Nyx like any contact.</span></span>
            </label>
          </fieldset>
          {mode === "number" && (
            <label className="cx-field"><span>Nyx’s number <em>the one with WhatsApp that Nyx will use</em></span>
              <input className="cx-search" inputMode="tel" placeholder="+1 555 010 0199" value={nyxNumber}
                onChange={(event) => setNyxNumber(event.target.value)} required />
            </label>
          )}
          <p className="cx-muted">
            WhatsApp links this PC as one of your devices, like WhatsApp Web, through an unofficial client. WhatsApp can
            restrict numbers that use unofficial clients — a separate number for Nyx keeps your own safe.
          </p>
          <button className="btn btn-primary" type="submit" disabled={!!busy || !phone.trim()}>
            {busy === "pair" ? "Asking WhatsApp for a code…" : "Pair My Phone"}
          </button>
        </form>
      )}

      {line.status === "pairing" && (
        <div className="wa-pair" aria-live="polite">
          {line.pair_code ? (
            <>
              <p className="cx-muted">On {line.mode === "number" ? "the phone with Nyx’s number" : "your phone"}, tap WhatsApp’s notification
                <b> “Enter code to link new device”</b> and confirm this code:</p>
              <output className="wa-code">{line.pair_code}</output>
              <p className="cx-muted">No notification? WhatsApp → Settings → Linked devices → Link a device → <b>Link with phone number instead</b>, then type the code.</p>
            </>
          ) : (
            <p className="cx-muted">Asking WhatsApp for a pairing code…</p>
          )}
          <button className="btn" onClick={() => void call("unlink", "/api/whatsapp/unlink")}>Cancel</button>
        </div>
      )}

      {linked && (
        <>
          <form className="wa-send" onSubmit={async (event) => {
            event.preventDefault();
            if (await call("send", "/api/whatsapp/send", { text }, 60000)) { setSent(text); setText(""); }
          }}>
            <input className="cx-search" placeholder="Text your phone from here…" value={text} onChange={(event) => setText(event.target.value)}
              aria-label="Message to your phone" disabled={!line.connected} />
            <button className="btn btn-primary" type="submit" disabled={!text.trim() || !line.connected || !!busy}>
              {busy === "send" ? "Sending…" : "Send"}
            </button>
          </form>
          {sent && <p className="cx-muted" role="status">Sent to {line.phone}.</p>}

          <div className="cx-settings">
            <label className="cx-switch">
              <button type="button" className="switch" role="switch" aria-checked={line.enabled}
                onClick={() => void call("enabled", "/api/whatsapp/settings", { enabled: !line.enabled })} />
              <span><b>Answer my texts</b><span className="cx-muted">Off: Nyx can still text you, but does not reply. /pause from the phone does the same.</span></span>
            </label>
            <label className="cx-switch">
              <button type="button" className="switch" role="switch" aria-checked={line.allow === "full"}
                onClick={() => void call("allow", "/api/whatsapp/settings", { allow: line.allow === "full" ? "chat" : "full" })} />
              <span><b>Full access from the phone</b><span className="cx-muted">Off (safer): answers, web, memory and pictures only. On: everything the PC chat can do — a lost phone could too.</span></span>
            </label>
          </div>

          {line.log.length > 0 && (
            <ol className="wa-log" aria-label="Recent messages">
              {line.log.slice(-6).map((entry, index) => (
                <li key={`${entry.at}-${index}`} data-dir={entry.dir}>
                  <span>{entry.dir === "in" ? "You" : "Nyx"} · {when(entry.at)}</span>{entry.text}
                </li>
              ))}
            </ol>
          )}
          <div className="wa-row">
            <p className="cx-muted">The whole conversation is in the chat called <b>WhatsApp</b>. Linked {when(line.paired_at)}.</p>
            <button className="btn" disabled={!!busy} onClick={() => void call("unlink", "/api/whatsapp/unlink")}>Unlink This PC</button>
          </div>
        </>
      )}
    </section>
  );
}
