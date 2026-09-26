/** Settings → Prompt refining, Predictions & autonomy, Updates.
 *
 * Every switch here changes what Nyx does without being asked, so each row says
 * plainly what happens when it is on (generative-ai.md: keep people in control,
 * communicate where AI is used).
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { UpdatesSection } from "./UpdatesSection";

interface OptimizerSettings {
  enabled: boolean; online: boolean; strength: number; show_in_chat: boolean;
  expand_short_tasks: boolean; polish_long_requests: boolean;
  stats: { turns: number; kept: number; expanded: number; polished: number; fell_back: number };
}
interface PredictSettings {
  predictions: boolean; predictive_text: boolean; next_tab_hints: boolean; model_hints: boolean;
  idle_tabs: boolean; auto_updates: "off" | "check" | "install"; detox_daily: boolean; detox_auto_approve: boolean; idle_minutes: number;
}
interface Preview { mode: string; optimized: string; engine: string; reason: string; ms: number; changed: boolean; checks: { notes?: string[] } }
interface UpdateStatus { ok: boolean; detail: string; behind?: number; dirty?: boolean; new?: string[]; installed?: boolean }

function Toggle({ label, hint, checked, onChange, disabled }: {
  label: string; hint: string; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean;
}) {
  const id = `set-${label.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className="field-row">
      <div className="field-row__text">
        <label className="field-row__label" htmlFor={id}>{label}</label>
        <div className="field-row__hint">{hint}</div>
      </div>
      <button id={id} className="switch" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)} />
    </div>
  );
}

export function IntelligenceSettings() {
  const [optimizer, setOptimizer] = useState<OptimizerSettings | null>(null);
  const [predict, setPredict] = useState<PredictSettings | null>(null);
  const [sample, setSample] = useState("make this all better");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [updates, setUpdates] = useState<UpdateStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void api.get<OptimizerSettings>("/api/optimizer/settings").then((r) => r.ok ? setOptimizer(r.data) : setError(r.error));
    void api.get<PredictSettings>("/api/predict/settings").then((r) => r.ok && setPredict(r.data));
  }, []);

  const saveOptimizer = async (patch: Partial<OptimizerSettings>) => {
    if (optimizer) setOptimizer({ ...optimizer, ...patch });
    const result = await api.put<OptimizerSettings>("/api/optimizer/settings", patch);
    if (result.ok) setOptimizer(result.data); else setError(result.error);
  };
  const savePredict = async (patch: Partial<PredictSettings>) => {
    if (predict) setPredict({ ...predict, ...patch });
    const result = await api.put<PredictSettings>("/api/predict/settings", patch);
    if (result.ok) {
      setPredict(result.data);
      try { localStorage.setItem("nyx.predict.text", result.data.predictions && result.data.predictive_text ? "1" : "0"); } catch { /* ignore */ }
    } else setError(result.error);
  };

  const runPreview = useCallback(async (text: string) => {
    if (!text.trim()) { setPreview(null); return; }
    const result = await api.post<Preview>("/api/optimizer/preview", { text });
    if (result.ok) setPreview(result.data);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => void runPreview(sample), 500);
    return () => window.clearTimeout(timer);
  }, [sample, runPreview]);

  const checkUpdates = async (install = false) => {
    setUpdates({ ok: true, detail: install ? "Installing…" : "Checking GitHub…" });
    const result = install ? await api.post<UpdateStatus>("/api/updates/install") : await api.get<UpdateStatus>("/api/updates");
    setUpdates(result.ok ? result.data : { ok: false, detail: result.error });
  };

  return (
    <>
      <div className="card">
        <div className="label" style={{ marginBottom: 4 }}>Prompt refining</div>
        <div className="field-row__hint" style={{ marginBottom: 8 }}>
          Two helper agents read what you type before Nyx does: one rewrites a short or vague request into a clear brief
          (or structures a long one), the other checks nothing you said was lost. Simple requests are never touched, and
          Nyx always sees your own words first.
        </div>
        {!optimizer ? <div className="muted">Loading…</div> : (
          <>
            <Toggle label="Refine my requests" hint="Off: Nyx gets exactly what you type." checked={optimizer.enabled}
              onChange={(v) => void saveOptimizer({ enabled: v })} />
            <Toggle label="Use an online model for refining" hint="Off: built-in rules only — instant and fully offline. On: a fast model when one answers within 8 s, rules otherwise."
              checked={optimizer.online} disabled={!optimizer.enabled} onChange={(v) => void saveOptimizer({ online: v })} />
            <Toggle label="Expand short requests" hint="“make this all better” becomes a brief with the goal, context and what a finished result looks like."
              checked={optimizer.expand_short_tasks} disabled={!optimizer.enabled} onChange={(v) => void saveOptimizer({ expand_short_tasks: v })} />
            <Toggle label="Structure long requests" hint="Long, detailed requests are only reorganized — every specific stays word for word."
              checked={optimizer.polish_long_requests} disabled={!optimizer.enabled} onChange={(v) => void saveOptimizer({ polish_long_requests: v })} />
            <Toggle label="Show refinements in chat" hint="Each answer shows what was added, with a one-click way to switch refining off."
              checked={optimizer.show_in_chat} disabled={!optimizer.enabled} onChange={(v) => void saveOptimizer({ show_in_chat: v })} />
            <div className="field-row">
              <div className="field-row__text">
                <div className="field-row__label">How much to refine</div>
                <div className="field-row__hint">Gentle leaves more alone; thorough briefs medium-length tasks too.</div>
              </div>
              <div className="segmented" role="group" aria-label="Refining strength">
                {[[1, "Gentle"], [2, "Balanced"], [3, "Thorough"]].map(([value, label]) => (
                  <button key={value} aria-pressed={optimizer.strength === value} disabled={!optimizer.enabled}
                    onClick={() => void saveOptimizer({ strength: value as number })}>{label}</button>
                ))}
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <label className="field-row__label" htmlFor="refine-sample">Try it</label>
              <input id="refine-sample" className="text-input" style={{ marginTop: 6 }} value={sample} onChange={(e) => setSample(e.target.value)} />
              {preview && (
                <div className="optimized-note" style={{ marginTop: 8 }}>
                  <div className="optimized-note__body" style={{ paddingTop: 8 }}>
                    <div className="optimized-note__label">
                      {preview.changed ? `${preview.mode === "polish" ? "Structured" : "Expanded"} · ${preview.engine} · ${preview.ms} ms` : `Left as typed — ${preview.reason}`}
                    </div>
                    {preview.changed && <div className="optimized-note__text is-refined">{preview.optimized}</div>}
                  </div>
                </div>
              )}
            </div>
            <div className="field-row__hint" style={{ marginTop: 8 }}>
              So far: {optimizer.stats.turns} requests · {optimizer.stats.kept} left alone · {optimizer.stats.expanded} expanded ·
              {" "}{optimizer.stats.polished} structured · {optimizer.stats.fell_back} online rewrites rejected by the checker.
            </div>
          </>
        )}
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 4 }}>Predictions &amp; autonomy</div>
        <div className="field-row__hint" style={{ marginBottom: 8 }}>
          Predictions are learned on this PC from how you use Nyx. The last group lets Nyx do quiet work while you're away.
        </div>
        {!predict ? <div className="muted">Loading…</div> : (
          <>
            <Toggle label="Predictions" hint="The master switch for everything below it in this group." checked={predict.predictions} onChange={(v) => void savePredict({ predictions: v })} />
            <Toggle label="Predictive text" hint="Suggests your next word while you type (Tab accepts)." checked={predict.predictive_text} disabled={!predict.predictions} onChange={(v) => void savePredict({ predictive_text: v })} />
            <Toggle label="Suggest the next tab" hint="A small shortcut to where you usually go next." checked={predict.next_tab_hints} disabled={!predict.predictions} onChange={(v) => void savePredict({ next_tab_hints: v })} />
            <Toggle label="Suggest models" hint="Names the outside model that has done best on requests like yours." checked={predict.model_hints} disabled={!predict.predictions} onChange={(v) => void savePredict({ model_hints: v })} />
            <div className="label" style={{ margin: "14px 0 2px" }}>While you're away</div>
            <div className="field-row">
              <div className="field-row__text">
                <div className="field-row__label">Away after</div>
                <div className="field-row__hint">Minutes without using Nyx before quiet work may start.</div>
              </div>
              <input type="range" className="slider" style={{ maxWidth: 160, ["--fill" as string]: `${((predict.idle_minutes - 5) / 235) * 100}%` }} min={5} max={240} step={5}
                value={predict.idle_minutes} aria-label="Away after (minutes)"
                onChange={(e) => setPredict({ ...predict, idle_minutes: Number(e.target.value) })}
                onPointerUp={() => void savePredict({ idle_minutes: predict.idle_minutes })} onKeyUp={() => void savePredict({ idle_minutes: predict.idle_minutes })} />
              <span className="field-row__value">{predict.idle_minutes} min</span>
            </div>
            <Toggle label="Make tabs Nyx thinks you need" hint="At most one a day, from a topic you keep coming back to. It's labelled, and you can delete it." checked={predict.idle_tabs} onChange={(v) => void savePredict({ idle_tabs: v })} />
            <Toggle label="Daily detox hour" hint="Once a day in your quiet hours: tidy what it learned, then a gentle self-improvement pass." checked={predict.detox_daily} onChange={(v) => void savePredict({ detox_daily: v })} />
            <Toggle label="Let the detox hour apply its changes" hint="Off: its findings wait for you in Improve. On: critic-reviewed, tested, and applied (each can be rolled back)." checked={predict.detox_auto_approve} disabled={!predict.detox_daily} onChange={(v) => void savePredict({ detox_auto_approve: v })} />
          </>
        )}
      </div>

      <div className="card">
        <div className="label" style={{ marginBottom: 4 }}>Updates</div>
        <div className="field-row__hint" style={{ marginBottom: 8 }}>New versions come from GitHub. Installing never overwrites local changes.</div>
        {predict && (
          <div className="field-row">
            <div className="field-row__text">
              <div className="field-row__label">Automatic updates</div>
              <div className="field-row__hint">Check tells you; install also applies them while you're away and restarts Nyx.</div>
            </div>
            <div className="segmented" role="group" aria-label="Automatic updates">
              {(["off", "check", "install"] as const).map((mode) => (
                <button key={mode} aria-pressed={predict.auto_updates === mode} onClick={() => void savePredict({ auto_updates: mode })}>{mode}</button>
              ))}
            </div>
          </div>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn btn-secondary" onClick={() => void checkUpdates(false)}>Check now</button>
          {updates?.behind ? <button className="btn btn-primary" onClick={() => void checkUpdates(true)} disabled={updates.dirty}>Install {updates.behind} update{updates.behind === 1 ? "" : "s"}</button> : null}
          {updates && <span className="field-row__hint" aria-live="polite">{updates.detail}</span>}
        </div>
        {updates?.new && updates.new.length > 0 && (
          <ul className="learn-feed" style={{ marginTop: 8 }}>{updates.new.map((line, i) => <li key={i}>{line}</li>)}</ul>
        )}
        <UpdatesSection />
      </div>
      {error && <div className="field-row__hint" style={{ color: "var(--color-warn)" }}>{error}</div>}
    </>
  );
}
