/** Big Kahuna — Identity 0 (Request S): the main brain every chat goes through, and what it has learned.
 *
 * The owner: "Identity 0 is our main brain. The overall supercore and the AI model powering it all … It will work
 * alongside Ollama at first then detach to work on its own. 2 models running at once to then 1."
 *
 * So the tab answers, in order: is it leading right now, who is it working with, who leads each kind of work and at
 * which stage (Collaborate → Twin → Solo), what it has learned from comparing answers, how its own model is doing,
 * and the switches — including "ID0 + All", the companion mode.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { Icon } from "../../components/chat/Icon";
import { Scoreboard, SuggestedTabs, TemplatesGallery, TrainingProgress } from "./KahunaExtras";
import "./kahuna.css";

interface Member { id: string; provider: string; model: string; local: boolean; free: boolean; vision: boolean; label: string }
interface Row { n: number; ok: number; avg_ms: number | null; wins: number; losses: number; ties: number; rating: number }
interface Overview {
  name: string; codename: string; version: string; available: boolean;
  settings: Record<string, unknown>;
  members: Member[];
  domains: Record<string, { stage: string; lead: string | null }>;
  last_plan: null | { domain: string; stage: string; lead: string; protocol: string; difficulty: number; speed?: string | null;
    shadow: string | null; helpers: string[] };
  experiences: { total?: number; learned?: number; shadowed?: number; verdicts?: Record<string, number>; judging_queue?: number };
  budgets: { api_left: number; judge_left: number };
  competence: { domains: Record<string, Record<string, Row>>; own_model: Record<string, { n: number; win_rate: number | null; bounds: number[] }>;
    graduated: Record<string, boolean>; rule: { min: number; lower_bound: number } };
  companion: { enabled: boolean };
  own_model: { current: null | { version: string; kind: string; params?: number }; ready: boolean;
    versions: { version: string; kind?: string; promoted?: boolean; metrics?: Record<string, number> }[];
    requirements?: { torch: boolean; cuda: boolean; gpu: string; vram_gb: number; missing: string[] }; note?: string };
}
interface Experience {
  id: string; ts: number; domain: string; protocol: string; prompt: string;
  lead: { member: string; ms: number; ok: boolean; text: string } | null;
  shadow: { member: string; ms: number; ok: boolean; text: string } | null;
  verdict: { winner: string; by: string; reason: string } | null; learned: boolean;
}

const STAGE_WORDS: Record<string, { label: string; hint: string }> = {
  collaborate: { label: "Collaborate", hint: "It picks the best of the other models; it has no own model for this yet." },
  twin: { label: "Twin", hint: "Its own model answers alongside the teacher and is judged side by side." },
  solo: { label: "Solo", hint: "Its own model has won here and leads on its own; the others are backups." },
};

const SETTING_TEXT: Record<string, { label: string; help: string; kind: "bool" | "number" | "choice"; min?: number; max?: number; step?: number; choices?: string[] }> = {
  enabled: { label: "Big Kahuna leads every chat", help: "Off sends chats straight to the models as before.", kind: "bool" },
  id0_all: { label: "ID0 + All (companion)", help: "Its own chat, thoughts in the background, and voice that acts before you finish talking.", kind: "bool" },
  panel_on_hard: { label: "Ask helpers on hard questions", help: "In areas where it is still weak, other models draft first and the lead writes the answer.", kind: "bool" },
  shadow_rate: { label: "Compare answers", help: "How often a second model also answers, so it learns who is better.", kind: "number", min: 0, max: 1, step: 0.05 },
  shadow_local_only: { label: "Compare with local models only", help: "No online calls at all for comparing and judging.", kind: "bool" },
  api_shadow_per_hour: { label: "Online calls for learning, per hour", help: "Keeps your free quotas safe.", kind: "number", min: 0, max: 60, step: 1 },
  auto_tabs: { label: "Create the tabs it predicts", help: "Off: it only suggests them.", kind: "bool" },
  auto_promote: { label: "Promote its own model when it wins", help: "Off: a new version waits for your click.", kind: "bool" },
  train_on_chats: { label: "Learn from my chats", help: "Private names, emails and keys are removed first.", kind: "bool" },
  layered_mode: { label: "Layer-by-layer for huge models", help: "AirLLM-style: only at Max power. Slow, but runs models bigger than your GPU.", kind: "choice", choices: ["off", "auto"] },
  ollama_autostart: { label: "Start Ollama when it is off", help: "The local model is its fastest partner.", kind: "bool" },
};

function seconds(ms: number | null | undefined): string {
  return ms == null ? "—" : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

function shortMember(id: string | null | undefined): string {
  if (!id) return "—";
  const [provider, ...rest] = id.split(":");
  const model = rest.join(":");
  if (provider === "self") return `Own model ${model}`;
  if (!model || model === "default") return provider;
  const tail = model.split("/").pop() ?? model;
  return `${tail} · ${provider}`;
}

export function KahunaPanel() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [experiences, setExperiences] = useState<Experience[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState("");
  const [training, setTraining] = useState("");

  const load = useCallback(async () => {
    const [main, recent] = await Promise.all([
      api.get<Overview>("/api/identity0"),
      api.get<{ experiences: Experience[] }>("/api/identity0/experiences?limit=12"),
    ]);
    if (main.ok) { setOverview(main.data); setError(""); } else setError(main.error);
    if (recent.ok) setExperiences(recent.data.experiences);
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    const off = onWorkspaceEvent((event) => {
      if (event.type === "identity0.stage" || event.type === "turn.state") void load();
    });
    return () => { window.clearInterval(timer); off(); };
  }, [load]);

  const change = async (key: string, value: unknown) => {
    setSaving(key);
    const result = await api.put<{ settings: Record<string, unknown> }>("/api/identity0/settings", { changes: { [key]: value } });
    setSaving("");
    if (!result.ok) { setError(result.error); return; }
    setOverview((current) => current ? { ...current, settings: result.data.settings } : current);
    window.dispatchEvent(new CustomEvent("nyx:kahuna-settings", { detail: result.data.settings }));
  };

  const makeMain = async () => {
    const result = await api.post("/api/identity0/main", {});
    if (!result.ok) setError(result.error); else void load();
  };

  const train = async () => {
    setTraining("Starting…");
    const result = await api.post<{ job: { id: string; message?: string } }>("/api/identity0/jobs", { kind: "train_nano", params: {} });
    setTraining(result.ok ? `Training started (${result.data.job.id}). Progress shows below.` : result.error);
  };

  if (!overview) {
    return <div className="kh"><p className="kh-muted">{error || "Waking Big Kahuna…"}</p></div>;
  }

  const settings = overview.settings;
  const leading = Boolean(settings.enabled) && overview.available;
  const domains = Object.entries(overview.domains);
  const rows = overview.competence.domains;
  const plan = overview.last_plan;

  return (
    <div className="kh">
      <header className="kh-head">
        <div>
          <h1>{overview.name} <span className="kh-second">{overview.codename}</span></h1>
          <p>The main brain. Every chat goes through it first: it picks which model answers, asks others when a question
            is hard, compares answers to learn who is best at what, and hands each area to its own model once that model wins.</p>
        </div>
        <div className="kh-head__side">
          <span className={`kh-pill${leading ? " is-on" : ""}`} role="status">
            <span className="kh-dot" aria-hidden="true" />{leading ? "Leading every chat" : settings.enabled ? "Waiting for a model" : "Off"}
          </span>
          <button className="kh-btn" onClick={() => void makeMain()} title="Make Big Kahuna the default in the chat's model menu">
            Make it the main brain
          </button>
        </div>
      </header>
      {error && <p className="kh-error" role="alert">{error}</p>}

      <section className="kh-card kh-card--wide" aria-label="Right now">
        <h2><Icon name="users" size={16} /> Working with</h2>
        <div className="kh-members">
          {overview.members.length === 0 && <p className="kh-muted">No model is reachable. Start Ollama or add a free key in Keys & Models.</p>}
          {overview.members.map((m) => (
            <span key={m.id} className={`kh-member${m.local ? " is-local" : ""}`} title={m.id}>
              {m.local ? "Local" : "Cloud"} · {shortMember(m.id)}{m.vision ? " · sees pictures" : ""}
            </span>
          ))}
        </div>
        {plan && (
          <p className="kh-plan">
            Last answer: <b>{shortMember(plan.lead)}</b> led in <b>{plan.domain}</b>
            {plan.speed ? ` (fast path: ${plan.speed})` : ""}{plan.helpers.length ? `, after drafts from ${plan.helpers.map(shortMember).join(" and ")}` : ""}
            {plan.shadow ? `; ${shortMember(plan.shadow)} answered too, for comparison` : ""}.
          </p>
        )}
        <p className="kh-muted">
          {overview.experiences.total ?? 0} answers seen · {overview.experiences.shadowed ?? 0} compared ·{" "}
          {overview.experiences.learned ?? 0} lessons learned · {overview.budgets.api_left} online learning calls left this hour
        </p>
      </section>

      <section className="kh-card" aria-label="Who leads each area">
        <h2><Icon name="sparkle" size={16} /> Who leads each area</h2>
        <ul className="kh-domains">
          {domains.map(([name, info]) => (
            <li key={name}>
              <span className="kh-domain">{name}</span>
              <span className={`kh-stage kh-stage--${info.stage}`} title={STAGE_WORDS[info.stage]?.hint}>{STAGE_WORDS[info.stage]?.label ?? info.stage}</span>
              <span className="kh-lead">{shortMember(info.lead)}</span>
            </li>
          ))}
        </ul>
        <p className="kh-muted">Collaborate → Twin → Solo. Its own model takes an area over after winning at least half of
          {" "}{overview.competence.rule.min}+ judged comparisons there, and hands it back if it slips.</p>
      </section>

      <section className="kh-card" aria-label="Its own model">
        <h2><Icon name="brain" size={16} /> Its own model</h2>
        {overview.own_model.current ? (
          <p>Running <b>{overview.own_model.current.version}</b> ({overview.own_model.current.kind}
            {overview.own_model.current.params ? `, ${(overview.own_model.current.params / 1e6).toFixed(1)}M parameters` : ""}).</p>
        ) : (
          <p className="kh-muted">Not serving yet. {overview.own_model.note ?? "Train the Nano seed to start the Twin stage."}</p>
        )}
        {overview.own_model.requirements && (
          <p className="kh-muted">GPU: {overview.own_model.requirements.gpu || "none found"}
            {overview.own_model.requirements.vram_gb ? ` · ${overview.own_model.requirements.vram_gb} GB` : ""}
            {overview.own_model.requirements.missing.length ? ` · missing: ${overview.own_model.requirements.missing.join(", ")}` : ""}</p>
        )}
        {overview.own_model.versions.length > 0 && (
          <ul className="kh-versions">
            {overview.own_model.versions.map((v) => (
              <li key={v.version}><b>{v.version}</b>{v.promoted ? " · serving" : ""}
                {v.metrics?.perplexity ? ` · perplexity ${v.metrics.perplexity.toFixed(1)}` : ""}</li>
            ))}
          </ul>
        )}
        <div className="kh-row">
          <button className="kh-btn kh-btn--primary" onClick={() => void train()}>Train the Nano seed</button>
          {training && <span className="kh-muted">{training}</span>}
        </div>
        <TrainingProgress />
      </section>

      <SuggestedTabs />

      <section className="kh-card kh-card--wide" aria-label="What it has learned">
        <h2><Icon name="memory" size={16} /> What it has learned</h2>
        {Object.keys(rows).length === 0 ? <p className="kh-muted">Nothing yet — it learns from every answer.</p> : (
          <div className="kh-table-wrap">
            <table className="kh-table">
              <thead><tr><th scope="col">Area</th><th scope="col">Model</th><th scope="col">Answers</th><th scope="col">Worked</th>
                <th scope="col">Avg time</th><th scope="col">Won / lost / tied</th><th scope="col">Your rating</th></tr></thead>
              <tbody>
                {Object.entries(rows).flatMap(([domain, members]) => Object.entries(members)
                  .sort((a, b) => b[1].n - a[1].n).slice(0, 4).map(([member, row]) => (
                    <tr key={`${domain}|${member}`}>
                      <td>{domain}</td><td title={member}>{shortMember(member)}</td><td>{row.n}</td>
                      <td>{row.n ? `${Math.round((row.ok / row.n) * 100)}%` : "—"}</td><td>{seconds(row.avg_ms)}</td>
                      <td>{row.wins} / {row.losses} / {row.ties}</td><td>{row.rating > 0 ? `+${row.rating}` : row.rating}</td>
                    </tr>
                  )))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="kh-card kh-card--wide" aria-label="Recent answers">
        <h2><Icon name="chat" size={16} /> Recent answers</h2>
        {experiences.length === 0 ? <p className="kh-muted">Chat with Nyx and they show up here.</p> : (
          <ul className="kh-exp">
            {experiences.map((e) => (
              <li key={e.id}>
                <p className="kh-exp__q">{e.prompt || "(internal call)"}</p>
                <p className="kh-muted">
                  {shortMember(e.lead?.member)} · {seconds(e.lead?.ms)} · {e.domain}
                  {e.shadow ? ` · compared with ${shortMember(e.shadow.member)}` : ""}
                  {e.verdict ? ` · ${e.verdict.winner === "tie" ? "a tie" : `${e.verdict.winner === "lead" ? "the lead" : "the other"} was better`}` : ""}
                  {e.learned ? " · learned" : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Scoreboard members={[...(overview.own_model.current ? [`self:${overview.own_model.current.version}`] : []),
                            ...overview.members.map((m) => m.id)]} />

      <TemplatesGallery />

      <section className="kh-card kh-card--wide" aria-label="Settings">
        <h2><Icon name="gear" size={16} /> Settings</h2>
        <div className="kh-settings">
          {Object.entries(SETTING_TEXT).map(([key, meta]) => {
            const value = settings[key];
            const id = `kh-set-${key}`;
            return (
              <div key={key} className="kh-setting">
                <div>
                  <label htmlFor={id}>{meta.label}</label>
                  <p className="kh-muted">{meta.help}</p>
                </div>
                {meta.kind === "bool" && (
                  <button id={id} role="switch" aria-checked={Boolean(value)} disabled={saving === key}
                          className={`kh-switch${value ? " is-on" : ""}`} onClick={() => void change(key, !value)}>
                    <span />
                  </button>
                )}
                {meta.kind === "number" && (
                  <input id={id} type="range" min={meta.min} max={meta.max} step={meta.step} value={Number(value)}
                         onChange={(ev) => void change(key, meta.step && meta.step < 1 ? Number(ev.target.value) : Math.round(Number(ev.target.value)))}
                         aria-valuetext={String(value)} />
                )}
                {meta.kind === "choice" && (
                  <select id={id} value={String(value)} onChange={(ev) => void change(key, ev.target.value)}>
                    {meta.choices?.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                )}
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
