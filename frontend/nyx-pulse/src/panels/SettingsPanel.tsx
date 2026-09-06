/** Settings tab (ROADMAP BB9, W3, Z1, Z5).
 *
 * Everything here is an expert override. Auto is correct for almost everyone, so
 * each control says what you give up by leaving it — a settings screen that
 * presents every option as equally valid pushes people into worse configurations.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";

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
            fontSize: 10, letterSpacing: ".06em", textTransform: "uppercase",
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
