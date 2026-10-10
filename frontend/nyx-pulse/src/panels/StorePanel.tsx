/** Add capability — the skill library (ROADMAP BB8, U1-U5).
 *
 * Skills attach themselves when a turn matches their triggers, so this screen is
 * about *managing* the library rather than switching things on for each use.
 * The preview box exists because automatic behaviour is only trustworthy if you
 * can see why it fired.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";
import { GithubSkills } from "./store/GithubSkills";

interface Skill {
  id: string;
  name: string;
  description: string;
  instructions: string;
  triggers: string[];
  source: "builtin" | "conversation" | "manual" | "imported";
  enabled: boolean;
  uses: number;
}

interface SkillsResponse {
  skills: Skill[];
  enabled: number;
  total: number;
}

interface PreviewHit {
  id: string;
  name: string;
  hits: number;
}

function SkillCard({ skill, onToggle, onRemove, highlighted }: {
  skill: Skill;
  onToggle: () => void;
  onRemove: () => void;
  highlighted: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card" style={{
      opacity: skill.enabled ? 1 : 0.55,
      borderLeft: highlighted ? "3px solid var(--color-accent)" : "3px solid transparent",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{skill.name}</span>
        {skill.source !== "builtin" && (
          <span style={{ fontSize: 12, textTransform: "uppercase", color: "var(--color-accent-2)" }}>
            {skill.source === "conversation" ? "from conversation" : skill.source}
          </span>
        )}
        {highlighted && (
          <span style={{ fontSize: 12, textTransform: "uppercase", color: "var(--color-accent)" }}>
            would attach
          </span>
        )}
        <span style={{
          marginLeft: "auto", fontSize: 12, fontFamily: "var(--font-mono)",
          color: "var(--color-neutral-600)",
        }}>
          {skill.uses} uses
        </span>
      </div>

      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginTop: 4, lineHeight: 1.55 }}>
        {skill.description || "No description."}
      </div>

      <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 7 }}>
        {skill.triggers.slice(0, 8).map((t) => (
          <span key={t} style={{
            fontSize: 12, fontFamily: "var(--font-mono)", padding: "1px 5px",
            borderRadius: 3, background: "var(--color-nav)", color: "var(--color-neutral-500)",
          }}>
            {t}
          </span>
        ))}
        {skill.triggers.length > 8 && (
          <span style={{ fontSize: 12, color: "var(--color-neutral-700)" }}>
            +{skill.triggers.length - 8}
          </span>
        )}
      </div>

      {open && (
        <div style={{
          marginTop: 9, padding: "8px 10px", borderRadius: 6, background: "var(--color-nav)",
          fontSize: 12, lineHeight: 1.6, color: "var(--color-neutral-400)",
        }}>
          {skill.instructions}
        </div>
      )}

      <div style={{ display: "flex", gap: 10, marginTop: 9 }}>
        <button className="btn" onClick={() => setOpen((v) => !v)}
          style={{ fontSize: 12, color: "var(--color-neutral-500)", padding: 0 }}>
          {open ? "hide instructions" : "show instructions"}
        </button>
        <button className="btn" onClick={onToggle}
          style={{ fontSize: 12, color: "var(--color-neutral-500)", padding: 0 }}>
          {skill.enabled ? "disable" : "enable"}
        </button>
        {skill.source !== "builtin" && (
          <button className="btn" onClick={onRemove}
            style={{ fontSize: 12, color: "var(--color-danger)", padding: 0 }}>
            delete
          </button>
        )}
      </div>
    </div>
  );
}

export function StorePanel() {
  const [data, setData] = useState<SkillsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  // "/skill …" and the command menu's "Create a skill instead" arrive with the words filled in.
  const [description, setDescription] = useState(() => {
    try {
      const draft = sessionStorage.getItem("nyx.skill.draft") ?? "";
      sessionStorage.removeItem("nyx.skill.draft");
      return draft;
    } catch { return ""; }
  });
  const [creating, setCreating] = useState(false);
  const [preview, setPreview] = useState("");
  const [hits, setHits] = useState<PreviewHit[]>([]);

  async function load() {
    const result = await api.get<SkillsResponse>("/api/skills");
    if (result.ok) { setData(result.data); setError(null); }
    else setError(result.error);
  }

  useEffect(() => { void load(); }, []);

  useEffect(() => {
    if (!preview.trim()) { setHits([]); return; }
    let alive = true;
    const timer = setTimeout(async () => {
      const result = await api.post<{ selected: PreviewHit[] }>(
        "/api/skills/preview", { message: preview },
      );
      if (alive && result.ok) setHits(result.data.selected);
    }, 300);
    return () => { alive = false; clearTimeout(timer); };
  }, [preview]);

  async function createFromDescription() {
    if (!description.trim()) return;
    setCreating(true);
    const result = await api.post("/api/skills/from-conversation", { description });
    setCreating(false);
    if (result.ok) { setDescription(""); setError(null); await load(); }
    else setError(result.error);
  }

  if (error && !data) return <PanelShell title="Add capability"><ErrorState error={error} /></PanelShell>;
  if (!data) return <PanelShell title="Add capability"><Loading what="Reading the skill library" /></PanelShell>;

  const highlighted = new Set(hits.map((h) => h.id));

  return (
    <PanelShell
      title="Add capability"
      subtitle={`${data.enabled} of ${data.total} skills enabled`}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {error && <ErrorState error={error} />}

        <div className="card" style={{ borderLeft: "3px solid var(--color-accent)" }}>
          <div className="label" style={{ marginBottom: 6 }}>Describe a new skill</div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginBottom: 10, lineHeight: 1.6 }}>
            Say what you want the agent to be good at. It writes the skill, and from then on it
            attaches itself whenever a message matches — no command, no setting.
          </div>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="e.g. helping me revise for SAT maths, focusing on similar triangles"
            style={{
              width: "100%", resize: "vertical", padding: "9px 11px",
              background: "var(--color-nav)", color: "var(--color-text)", border: "none",
              borderRadius: "var(--radius)", boxShadow: "inset 0 0 0 1px var(--color-divider)",
              font: "inherit", fontSize: 13, marginBottom: 9,
            }}
          />
          <button className="btn btn-primary" disabled={creating || !description.trim()}
            onClick={() => void createFromDescription()}
            style={{ opacity: creating || !description.trim() ? 0.5 : 1 }}>
            {creating ? "Writing the skill…" : "Create skill"}
          </button>
        </div>

        <GithubSkills onAdded={() => void load()} />

        <div className="card">
          <div className="label" style={{ marginBottom: 6 }}>Which skills would this message use?</div>
          <input
            value={preview}
            onChange={(e) => setPreview(e.target.value)}
            placeholder="Type a message to see what attaches"
            style={{
              width: "100%", padding: "8px 10px", background: "var(--color-nav)",
              color: "var(--color-text)", border: "none", borderRadius: "var(--radius)",
              boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 13,
            }}
          />
          {preview.trim() && (
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginTop: 8 }}>
              {hits.length === 0
                ? "Nothing would attach — this turn costs no extra prompt."
                : hits.map((h) => `${h.name} (${h.hits} trigger${h.hits === 1 ? "" : "s"})`).join(", ")}
            </div>
          )}
        </div>

        {data.skills.map((skill) => (
          <SkillCard
            key={skill.id}
            skill={skill}
            highlighted={highlighted.has(skill.id)}
            onToggle={async () => {
              await api.post(`/api/skills/${skill.id}/enabled`, { enabled: !skill.enabled });
              await load();
            }}
            onRemove={async () => {
              const result = await api.del(`/api/skills/${skill.id}`);
              if (!result.ok) setError(result.error);
              await load();
            }}
          />
        ))}
      </div>
    </PanelShell>
  );
}
