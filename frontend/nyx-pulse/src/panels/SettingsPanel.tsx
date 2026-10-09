/** Settings tab (ROADMAP BB9, W3, Z1, Z5).
 *
 * Everything here is an expert override. Auto is correct for almost everyone, so
 * each control says what you give up by leaving it — a settings screen that
 * presents every option as equally valid pushes people into worse configurations.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";
import { engine, type EngineStatus } from "../engine";
import { VoicesSection } from "./VoicesSection";
import { ClapPanel } from "../components/clap/ClapPanel";
import { BackgroundsSection } from "./BackgroundsSection";
import { StorageSection } from "./StorageSection";
import { ContentModeSection } from "./ContentModeSection";
import { IntelligenceSettings } from "./IntelligenceSettings";
import { ModsSection } from "./ModsSection";

interface SpeedMode {
  id: string;
  label: string;
  description: string;
}

interface SpeedResponse {
  mode: string;
  modes: SpeedMode[];
}

interface Personality {
  id: string;
  display_name: string;
  description: string;
}

interface PersonalitiesResponse {
  presets?: Personality[];
  custom?: unknown;
  /** Id of the personality the engine currently has applied; "" means default. */
  active?: string;
}

function Section({ title, hint, children }: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card">
      <div className="label" style={{ marginBottom: hint ? 4 : 10 }}>{title}</div>
      {hint && (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginBottom: 12, lineHeight: 1.6 }}>
          {hint}
        </div>
      )}
      {children}
    </div>
  );
}

function Choice({ selected, label, description, badge, onSelect }: {
  selected: boolean;
  label: string;
  description: string;
  badge?: string;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      style={{
        display: "block", width: "100%", textAlign: "left", padding: "10px 12px",
        marginBottom: 8, borderRadius: "var(--radius)",
        background: selected ? "var(--color-accent-900)" : "var(--color-nav)",
        boxShadow: selected ? "inset 0 0 0 1px var(--color-accent-700)" : "none",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
        <span style={{ fontSize: 13, fontWeight: selected ? 600 : 400 }}>{label}</span>
        {badge && (
          <span style={{
            fontSize: 11, letterSpacing: ".06em", textTransform: "uppercase",
            color: "var(--color-accent)",
          }}>
            {badge}
          </span>
        )}
      </div>
      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.55 }}>
        {description}
      </div>
    </button>
  );
}

/** Engine: start with Windows, restart, turn off.
 *
 * The engine used to be something you started by hand in a terminal and kept a
 * window open for. It now runs in the background with a tray icon; this is the
 * in-app view of the same controls.
 */
function EngineSection() {
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [busy, setBusy] = useState<"" | "autostart" | "restart" | "stop">("");
  const [note, setNote] = useState("");

  useEffect(() => {
    let alive = true;
    void engine.status().then((result) => {
      if (alive && result.ok) setStatus(result.data);
    });
    return () => { alive = false; };
  }, []);

  async function toggleAutostart() {
    if (!status || busy) return;
    setBusy("autostart");
    const result = await engine.setAutostart(!status.autostart);
    setBusy("");
    if (result.ok) setStatus(result.data);
    else setNote(result.error);
  }

  async function restart() {
    if (busy) return;
    setBusy("restart");
    const result = await engine.restart();
    setNote(result.ok ? "Restarting… this page reconnects by itself in a few seconds." : result.error);
    if (!result.ok) setBusy("");
  }

  async function turnOff() {
    if (busy) return;
    setBusy("stop");
    const result = await engine.stop();
    setNote(result.ok ? "Turning Nyx off…" : result.error);
    if (!result.ok) setBusy("");
  }

  if (!status) return null;
  const managed = status.managed;

  return (
    <Section
      title="Engine"
      hint="Nyx runs on this computer in the background — look for its icon near the clock."
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={status.autostart}
            disabled={busy === "autostart"}
            onChange={() => void toggleAutostart()}
            style={{ width: 16, height: 16, accentColor: "var(--color-accent)" }}
          />
          <span>
            Start Nyx when Windows starts
            <span style={{ display: "block", fontSize: 12, color: "var(--color-neutral-500)" }}>
              {status.autostart
                ? "On — Nyx is ready as soon as you sign in. No clicks at all."
                : "Off — start Nyx from the desktop shortcut when you want it."}
            </span>
          </span>
        </label>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-secondary" disabled={!managed || busy !== ""} onClick={() => void restart()}>
            {busy === "restart" ? "Restarting…" : "Restart engine"}
          </button>
          <button className="btn btn-secondary" disabled={!managed || busy !== ""} onClick={() => void turnOff()}
            style={{ color: "var(--color-warn)" }}>
            {busy === "stop" ? "Turning off…" : "Turn off Nyx"}
          </button>
        </div>

        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
          {managed
            ? `Running on port ${status.port ?? "?"} · started by the Nyx launcher.`
            : "This engine was started by hand (a developer server), so restart and turn off are handled there."}
          {!status.link_registered && (
            <span style={{ display: "block", color: "var(--color-warn)" }}>
              One-click start is not set up on this computer yet — double-click “Start Nyx” in the Nyx folder once.
            </span>
          )}
        </div>
        {note && <div style={{ fontSize: 12, color: "var(--color-accent-400)" }} aria-live="polite">{note}</div>}
      </div>
    </Section>
  );
}

export function SettingsPanel() {
  const [speed, setSpeed] = useState<SpeedResponse | null>(null);
  const [personalities, setPersonalities] = useState<Personality[]>([]);
  const [activePersonality, setActivePersonality] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    void Promise.all([
      api.get<SpeedResponse>("/api/speed"),
      api.get<PersonalitiesResponse>("/api/personalities"),
    ]).then(([s, p]) => {
      if (!alive) return;
      if (s.ok) setSpeed(s.data);
      else setError(s.error);
      if (p.ok) {
        setPersonalities(p.data.presets ?? []);
        // Reflect what the server actually has applied. Previously this
        // always started at Default regardless of the real setting.
        setActivePersonality(p.data.active ?? "");
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  async function chooseSpeed(mode: string) {
    if (!speed || saving) return;
    setSaving(true);
    const previous = speed.mode;
    setSpeed({ ...speed, mode });          // optimistic
    const result = await api.post<{ mode: string }>("/api/speed", { mode });
    setSaving(false);
    if (!result.ok) {
      setSpeed({ ...speed, mode: previous });  // roll back on failure
      setError(result.error);
    }
  }

  async function choosePersonality(id: string) {
    if (saving) return;
    setSaving(true);
    const previous = activePersonality;
    setActivePersonality(id);                       // optimistic
    const result = await api.post<{ active: string }>("/api/personality", { id });
    setSaving(false);
    if (!result.ok) {
      setActivePersonality(previous);               // roll back on failure
      setError(result.error);
    }
  }

  if (error && !speed) return <PanelShell title="Settings"><ErrorState error={error} /></PanelShell>;
  if (!speed) return <PanelShell title="Settings"><Loading what="Reading settings" /></PanelShell>;

  return (
    <PanelShell title="Settings" subtitle="Auto is the default — these are expert overrides">
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {error && <ErrorState error={error} />}

        <EngineSection />

        <IntelligenceSettings />

        <Section
          title="Mods"
          hint="Your lasting changes to Nyx, one per wish. Ask Nyx for one in chat; pause or remove it here and what it changed is undone."
        >
          <ModsSection />
        </Section>

        <Section
          title="Response speed"
          hint="Auto decides per turn. The other two are useful when you know what you want, and each costs something."
        >
          {speed.modes.map((m) => (
            <Choice
              key={m.id}
              selected={speed.mode === m.id}
              label={m.label}
              description={m.description}
              badge={m.id === "auto" ? "recommended" : undefined}
              onSelect={() => void chooseSpeed(m.id)}
            />
          ))}
        </Section>

        <Section
          title="Personality"
          hint="Changes how replies sound. It does not change what the agent can do, and it never overrides correctness."
        >
          {personalities.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
              No personality presets available.
            </div>
          ) : (
            <>
              <Choice
                selected={activePersonality === ""}
                label="Default"
                description="Concise and direct. No styling applied."
                badge="recommended"
                onSelect={() => void choosePersonality("")}
              />
              {personalities.map((p) => (
                <Choice
                  key={p.id}
                  selected={activePersonality === p.id}
                  label={p.display_name}
                  description={p.description}
                  onSelect={() => void choosePersonality(p.id)}
                />
              ))}
              <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 8, lineHeight: 1.6 }}>
                Applies to every conversation on this engine, immediately. Persisting it
                per account, the second personality axis (how the agent <em>behaves</em>, not
                just how it sounds), and per-sub-agent personalities are still to build —
                roadmap Z2, Z3.
              </div>
            </>
          )}
        </Section>

        <Section title="Background">
          <BackgroundsSection />
        </Section>

        <Section title="Voices">
          <VoicesSection />
        </Section>

        <Section title="Clap" hint="Sounds Nyx answers to when you are away, offline, or using the background voice.">
          <ClapPanel />
        </Section>

        <Section title="Storage">
          <StorageSection />
        </Section>

        <Section title="Content">
          <ContentModeSection />
        </Section>

        <Section title="Not built yet">
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.7 }}>
            Account management and beta invites are backend-only for now — use{" "}
            <code style={{ fontFamily: "var(--font-mono)" }}>admin_setup.py</code> from the
            project folder. Training modes (roadmap Y), permission grants for machine control
            (V), and the skills library (U) have no UI yet.
          </div>
        </Section>
      </div>
    </PanelShell>
  );
}
