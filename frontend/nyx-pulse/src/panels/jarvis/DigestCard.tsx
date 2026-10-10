/** Morning Digest on the Jarvis page (morning_digest.py): the last briefing, Brief Me Now, Play, and its settings. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { speakText } from "../../voice/voicePlayer";

interface Digest { at: number; text: string; facts: Record<string, string[]>; skipped: Record<string, string> }
interface Settings {
  enabled: boolean; time: string; city: string; topics: string[]; symbols: string[];
  sources: Record<string, boolean>; whatsapp: boolean; last: Partial<Digest>;
}

const SOURCE_WORDS: Record<string, string> = {
  calendar: "Calendar", email: "Email", weather: "Weather", news: "News", markets: "Markets", nyx: "Offices",
};

export function DigestCard() {
  const [conf, setConf] = useState<Settings | null>(null);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const r = await api.get<Settings>("/api/jarvis/digest");
    if (r.ok) setConf(r.data); else setError(r.error);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const save = async (changes: Partial<Settings>) => {
    const r = await api.put<Settings>("/api/jarvis/digest", changes);
    if (r.ok) setConf(r.data); else setError(r.error);
  };

  const run = async () => {
    setBusy(true); setError("");
    const r = await api.post<Digest>("/api/jarvis/digest/run", {}, 180000);
    setBusy(false);
    if (!r.ok) { setError(r.error); return; }
    await load();
    try { await speakText(r.data.text); } catch { /* no voice: it is on screen */ }
  };

  if (!conf) return null;
  const last = conf.last?.text ? (conf.last as Digest) : null;

  return (
    <section className="jv-card" aria-labelledby="jv-digest">
      <h2 id="jv-digest">Morning Digest <span>{conf.enabled ? `daily at ${conf.time}` : ""}</span></h2>
      <div className="jv-row">
        <button className="btn btn-primary" disabled={busy} onClick={() => void run()}>{busy ? "Gathering…" : "Brief Me Now"}</button>
        {last && <button className="btn btn-secondary" onClick={() => void speakText(last.text)}>Play Last</button>}
        <button className="btn btn-secondary" onClick={() => setOpen((v) => !v)} aria-expanded={open}>Settings</button>
      </div>
      {error && <p className="jv-error">{error}</p>}
      {last ? (
        <>
          <p className="jv-digest">{last.text}</p>
          <p className="jv-muted">
            {new Date(last.at * 1000).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}
            {Object.keys(last.skipped ?? {}).length > 0 && ` · not included: ${Object.keys(last.skipped).map((k) => SOURCE_WORDS[k] ?? k).join(", ")}`}
          </p>
        </>
      ) : <p className="jv-muted">No digest yet. Brief Me Now makes one from what is connected.</p>}

      {open && (
        <form className="jv-settings" onSubmit={(e) => e.preventDefault()}>
          <label className="jv-check"><input type="checkbox" checked={conf.enabled} onChange={(e) => void save({ enabled: e.target.checked })} /> Every day at</label>
          <input type="time" value={conf.time} onChange={(e) => void save({ time: e.target.value })} aria-label="Digest time" />
          <label>City for the weather <input defaultValue={conf.city} onBlur={(e) => void save({ city: e.target.value })} placeholder="Austin" /></label>
          <label>News about <input defaultValue={conf.topics.join(", ")} onBlur={(e) => void save({ topics: e.target.value.split(",") })} placeholder="AI, F1" /></label>
          <label>Prices <input defaultValue={conf.symbols.join(", ")} onBlur={(e) => void save({ symbols: e.target.value.split(",") })} placeholder="SPY, AAPL" /></label>
          <fieldset>
            <legend className="jv-muted">Include</legend>
            {Object.keys(SOURCE_WORDS).map((key) => (
              <label key={key} className="jv-check">
                <input type="checkbox" checked={conf.sources[key] !== false} onChange={(e) => void save({ sources: { ...conf.sources, [key]: e.target.checked } })} />
                {SOURCE_WORDS[key]}
              </label>
            ))}
          </fieldset>
          <label className="jv-check"><input type="checkbox" checked={conf.whatsapp} onChange={(e) => void save({ whatsapp: e.target.checked })} /> Also text it to my phone (WhatsApp)</label>
          <p className="jv-muted">Email subjects and headlines go to your fast model to write the spoken version.</p>
        </form>
      )}
    </section>
  );
}
