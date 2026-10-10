/** Voices — pick how Nyx and each agent sound, and hear it before choosing.
 *
 * Every role (Nyx's replies, the narrator, each default agent) has its own
 * neural voice; Nyx can also change them from chat (`set_voice_for`).
 * `voice.roles.changed` keeps open windows in step. Styling: design pass.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { speakText } from "../voice/voicePlayer";
import { VoicePicker } from "../components/voice/VoicePicker";

interface Voice { id: string; name: string; locale: string; gender: string; engine: string }

const ROLE_LABELS: Record<string, string> = {
  reply: "Nyx (replies)", narrator: "Narrator", manager: "Manager", coder: "Coder", web_design: "Web Design",
  app_design: "App Design", finance: "Finance", educator: "Educator", tech: "Tech", hardware: "Hardware", news: "News",
  researcher: "Researcher", writer_editor: "Writer & Editor", email_comms: "Email & Comms",
  computer_operator: "Computer Operator", data_analyst: "Data Analyst", security: "Security", planner: "Planner",
  creative_games: "Creative & Games", travel: "Travel",
};

export function VoicesSection() {
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [voices, setVoices] = useState<Voice[]>([]);
  const [windowsVoices, setWindowsVoices] = useState<Voice[]>([]);
  const [locale, setLocale] = useState("en");
  const [message, setMessage] = useState("");
  const [picking, setPicking] = useState("");

  const loadRoles = useCallback(async () => {
    const r = await api.get<{ roles: Record<string, string> }>("/api/voice/roles");
    if (r.ok) setRoles(r.data.roles);
  }, []);

  useEffect(() => { void loadRoles(); }, [loadRoles]);
  useEffect(() => onWorkspaceEvent((e) => { if (e.type === "voice.roles.changed") void loadRoles(); }), [loadRoles]);
  useEffect(() => {
    void api.get<{ voices: Voice[]; windows_voices: Voice[] }>(`/api/voice/neural-voices?locale=${encodeURIComponent(locale)}`)
      .then((r) => { if (r.ok) { setVoices(r.data.voices); setWindowsVoices(r.data.windows_voices); } });
  }, [locale]);

  const options = useMemo(() => {
    const ids = new Set(voices.map((v) => v.id));
    const extra = Object.values(roles).filter((id) => !ids.has(id)).map((id) => ({ id, name: id, locale: "", gender: "", engine: "edge" }));
    return [...voices, ...extra, ...windowsVoices];
  }, [voices, windowsVoices, roles]);

  async function choose(role: string, voice: string) {
    const r = await api.put<{ roles: Record<string, string> }>(`/api/voice/roles/${role}`, { voice });
    if (r.ok) { setRoles(r.data.roles); setMessage(""); } else setMessage(r.error);
  }

  async function preview(role: string) {
    setMessage("");
    const label = ROLE_LABELS[role] ?? role;
    try {
      await speakText(`Hi, I'm ${label === "Nyx (replies)" ? "Nyx" : `the ${label} agent`}. This is how I sound.`, { role });
    } catch (error) {
      setMessage(`Could not play: ${(error as Error).message}`);
    }
  }

  return (
    <div>
      <p style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6, margin: "0 0 8px" }}>
        Neural voices need internet; Windows voices work offline. Press ▶ to hear a role's voice, or Change to hover through the voices and hear each one. You can also ask Nyx:
        “give the coder a British voice”.
      </p>
      <label className="keys-field" style={{ maxWidth: 220, marginBottom: 8 }}>
        <span>Language</span>
        <select value={locale} onChange={(e) => setLocale(e.target.value)}>
          {[["en", "English"], ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["hi", "Hindi"], ["bn", "Bengali"],
            ["ja", "Japanese"], ["zh", "Chinese"], ["", "All languages"]].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </label>
      <div style={{ display: "grid", gap: 6 }}>
        {Object.entries(roles).map(([role, voice]) => (
          <div key={role} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, minWidth: 140 }}>{ROLE_LABELS[role] ?? role}</span>
            <select className="field-control" aria-label={`Voice for ${ROLE_LABELS[role] ?? role}`} value={voice}
              onChange={(e) => void choose(role, e.target.value)}
              style={{ flex: 1, minWidth: 180 }}>
              {options.map((v) => (
                <option key={`${v.engine}-${v.id}`} value={v.id}>
                  {v.name}{v.locale ? ` · ${v.locale}` : ""}{v.gender ? ` · ${v.gender}` : ""}{v.engine === "sapi" ? " · offline" : ""}
                </option>
              ))}
            </select>
            <button className="btn btn-secondary btn-sm" type="button" aria-label={`Preview ${ROLE_LABELS[role] ?? role}`}
              onClick={() => void preview(role)}>▶</button>
            <button className="btn btn-secondary btn-sm" type="button" aria-expanded={picking === role}
              onClick={() => setPicking((p) => (p === role ? "" : role))}>{picking === role ? "Done" : "Change"}</button>
            {picking === role && (
              <div style={{ flexBasis: "100%" }}>
                <VoicePicker voices={options} value={voice} label={`Voices for ${ROLE_LABELS[role] ?? role}`}
                  onPick={(id) => void choose(role, id)} />
              </div>
            )}
          </div>
        ))}
      </div>
      {message && <p className="keys-message is-error" aria-live="polite">{message}</p>}
    </div>
  );
}
