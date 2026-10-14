/** Settings → Phone: let a phone on the home network read and write the chats, connected with a one-minute key.
 *
 * The phone server is off until the owner switches it on here. "Show a key" makes a key that works once and stops
 * working after 60 seconds; the phone opens the address shown below, types the key, and is remembered after that
 * (and can be removed here at any time).
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

interface Device { id: string; name: string; created: number; last_seen: number }
interface PhoneState {
  enabled: boolean;
  running: boolean;
  port: number;
  error: string;
  urls: string[];
  key_seconds_left: number;
  devices: Device[];
}

function ago(seconds: number): string {
  if (!seconds) return "never";
  const gap = Math.max(0, Date.now() / 1000 - seconds);
  if (gap < 90) return "just now";
  if (gap < 5400) return `${Math.round(gap / 60)} min ago`;
  if (gap < 129600) return `${Math.round(gap / 3600)} h ago`;
  return `${Math.round(gap / 86400)} days ago`;
}

export function PhoneSection() {
  const [state, setState] = useState<PhoneState | null>(null);
  const [error, setError] = useState("");
  const [key, setKey] = useState("");
  const [left, setLeft] = useState(0);

  const load = useCallback(async () => {
    const result = await api.get<PhoneState>("/api/phone");
    if (result.ok) setState(result.data);
    else setError(result.error);
  }, []);

  useEffect(() => { void load(); }, [load]);

  // The countdown is local; the server decides when the key really stops, and a refresh shows who connected.
  useEffect(() => {
    if (left <= 0) return;
    const timer = window.setTimeout(() => {
      setLeft(left - 1);
      if (left - 1 <= 0) setKey("");
      if ((left - 1) % 4 === 0 || left - 1 <= 0) void load();
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [left, load]);

  async function toggle(enabled: boolean) {
    setError("");
    const result = await api.post<PhoneState>("/api/phone/gateway", { enabled });
    if (!result.ok) { setError(result.error); return; }
    setState(result.data);
    if (!enabled) { setKey(""); setLeft(0); }
  }

  async function showKey() {
    setError("");
    const result = await api.post<PhoneState & { key: string; expires_in: number }>("/api/phone/key");
    if (!result.ok) { setError(result.error); return; }
    setState(result.data);
    setKey(result.data.key);
    setLeft(result.data.expires_in);
  }

  async function remove(id: string) {
    const result = await api.del<PhoneState>(`/api/phone/devices/${id}`);
    if (result.ok) setState(result.data);
    else setError(result.error);
  }

  return (
    <div className="card">
      <div className="label" style={{ marginBottom: 4 }}>Phone</div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
        See your chats and write to them from your phone while it is on the same Wi-Fi as this computer. It is off
        until you turn it on, only phones you connect with a key can use it, and it can talk, search and read but not
        change this computer.
      </div>
      {error && <div role="alert" style={{ color: "var(--color-danger, #c0392b)", fontSize: 12, marginTop: 8 }}>{error}</div>}
      {state?.error && <div role="alert" style={{ color: "var(--color-danger, #c0392b)", fontSize: 12, marginTop: 8 }}>{state.error}</div>}
      {!state && !error && <div style={{ fontSize: 12, marginTop: 10 }}>Reading phone settings…</div>}
      {state && (
        <>
          <div style={{ display: "flex", gap: 6, marginTop: 14 }}>
            <button type="button" className={state.running ? "btn" : "btn ghost"} aria-pressed={state.running}
              style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => void toggle(!state.running)}>
              {state.running ? "Allow my phone: on" : "Allow my phone: off"}
            </button>
          </div>
          {state.running && (
            <>
              <div style={{ fontSize: 12, marginTop: 12 }}>
                On your phone open:{" "}
                {state.urls.length
                  ? state.urls.map((url) => <strong key={url} style={{ marginRight: 8 }}>{url}</strong>)
                  : <span>this computer's address, port {state.port} (it could not work out the address itself)</span>}
              </div>
              <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 12 }}>
                <button type="button" className="btn ghost" style={{ fontSize: 12 }} onClick={() => void showKey()}>
                  {key ? "Make a new key" : "Show a key"}
                </button>
                {key && (
                  <span role="status" style={{ fontSize: 18, letterSpacing: 2, fontWeight: 600 }}>
                    {key} <span style={{ fontSize: 12, fontWeight: 400, letterSpacing: 0 }}>({left}s left, works once)</span>
                  </span>
                )}
              </div>
            </>
          )}
          {state.devices.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginBottom: 6 }}>Connected phones</div>
              {state.devices.map((device) => (
                <div key={device.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, marginBottom: 4 }}>
                  <span style={{ flex: 1 }}>{device.name} <span style={{ color: "var(--color-neutral-500)" }}>· last used {ago(device.last_seen)}</span></span>
                  <button type="button" className="btn ghost" style={{ fontSize: 12 }} onClick={() => void remove(device.id)}>Remove</button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
