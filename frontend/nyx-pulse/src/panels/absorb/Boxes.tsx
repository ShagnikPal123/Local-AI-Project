/** The expandable boxes of Data Absorption (Request R8): a finding, or a change Nyx wants to make to itself.
 *
 * "Make sure each big idea is condensed into separate boxes which can be expanded to see what is in there and the user
 * approves." A box shows the idea in one line; opening it shows exactly what would change. The approve button names
 * the action ("Add Skill", "File for Review"), and nothing happens to Nyx until it is pressed.
 */

import { useState, type ReactNode } from "react";
import { Markdown } from "../../components/chat/Markdown";
import type { Finding, Suggestion } from "./types";

const KIND_LABEL: Record<Suggestion["kind"], string> = {
  skill: "Skill", agent: "New agent", agent_feature: "Agent feature", speedup: "Speed-up", dataset: "Training set", local_model: "Local model",
};
const APPROVE_LABEL: Record<Suggestion["kind"], string> = {
  skill: "Add Skill", agent: "Create Agent", agent_feature: "Update Agent", speedup: "File for Review", dataset: "Save Training Set",
  local_model: "Build Local Model",
};
const WHAT_HAPPENS: Record<Suggestion["kind"], string> = {
  skill: "Nyx follows these instructions whenever a request matches the triggers. You can turn it off in Add capability → Skills.",
  agent: "A new sub-agent joins the team, appears in Sub-agents and as a /command, and Nyx can hand it work.",
  agent_feature: "The agent's expertise and instructions are extended; the rest of its settings stay as they are.",
  speedup: "It is filed in Improve → Review changes. There it is researched, written, tested in a sandbox and applied only after you approve it again.",
  dataset: "Question-and-answer pairs from this run are saved as a small JSONL file for fine-tuning a local model later.",
  local_model: "Ollama builds a copy of a local model whose instructions include what Nyx studied, so it answers from it offline.",
};

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="ab-label">{label}</div>
      {children}
    </div>
  );
}

function SpecView({ item }: { item: Suggestion }) {
  const spec = item.spec as Record<string, unknown>;
  const text = (key: string) => (spec[key] === undefined || spec[key] === null ? "" : Array.isArray(spec[key]) ? (spec[key] as unknown[]).join(", ") : String(spec[key]));
  switch (item.kind) {
    case "skill":
      return (
        <>
          <Row label="Name">{text("name") || item.title}</Row>
          {text("description") && <Row label="Description">{text("description")}</Row>}
          <Row label="Instructions Nyx will follow"><pre>{text("instructions")}</pre></Row>
          {text("triggers") && <Row label="Used when a request mentions">{text("triggers")}</Row>}
        </>
      );
    case "agent":
      return (
        <>
          <Row label="Agent">{text("emoji")} {text("name")}</Row>
          <Row label="Goal">{text("goal")}</Row>
          {text("expertise") && <Row label="Expertise">{text("expertise")}</Row>}
          {text("instructions") && <Row label="Instructions"><pre>{text("instructions")}</pre></Row>}
        </>
      );
    case "agent_feature":
      return (
        <>
          <Row label="Agent">{text("agent")}</Row>
          {text("add_expertise") && <Row label="Adds expertise">{text("add_expertise")}</Row>}
          {text("add_instructions") && <Row label="Adds instructions"><pre>{text("add_instructions")}</pre></Row>}
        </>
      );
    case "speedup":
      return (
        <>
          <Row label="Change">{text("description") || item.why}</Row>
          <Row label="File">{text("target") || "Nyx decides while researching it"}</Row>
        </>
      );
    case "local_model":
      return <Row label="Model">{text("name") || "nyx-absorbed"} · built on {text("base") || "the first installed Ollama model"} · up to {text("facts")} facts</Row>;
    default:
      return <Row label="Size">{text("examples")} examples</Row>;
  }
}

export function SuggestionBox({ item, onDecide, defaultOpen = false }: {
  item: Suggestion;
  onDecide: (id: string, decision: "approve" | "dismiss") => Promise<void>;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState<"approve" | "dismiss" | null>(null);
  const bodyId = `sg-${item.id}`;
  const decide = async (decision: "approve" | "dismiss") => {
    setBusy(decision);
    await onDecide(item.id, decision);
    setBusy(null);
  };
  return (
    <div className={`ab-box${item.state === "applied" ? " is-good" : item.state === "failed" ? " is-risk" : ""}`}>
      <button type="button" className="ab-box__head" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen((v) => !v)}>
        <span className="ab-box__chev" aria-hidden="true">▶</span>
        <span className="ab-box__title">{item.title}</span>
        <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span className="ab-box__kind">{KIND_LABEL[item.kind] ?? item.kind}</span>
          <span className={`ab-state is-${item.state}`}>{item.state === "pending" ? "Waiting for you" : item.state}</span>
        </span>
        {item.why && <span className="ab-box__gist">{item.why}</span>}
      </button>
      {open && (
        <div className="ab-box__body" id={bodyId}>
          <SpecView item={item} />
          <p className="ab-note">{WHAT_HAPPENS[item.kind]}</p>
          {item.result && <p className={`ab-box__result is-${item.state}`} role="status">{item.result}</p>}
          {item.state === "pending" && (
            <div className="ab-actions">
              <button className="ab-btn is-primary" disabled={busy !== null} onClick={() => void decide("approve")}>
                {busy === "approve" ? "Working…" : APPROVE_LABEL[item.kind] ?? "Approve"}
              </button>
              <button className="ab-btn" disabled={busy !== null} onClick={() => void decide("dismiss")}>Dismiss</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function FindingBox({ finding, evidence, defaultOpen = false }: { finding: Finding; evidence?: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = `fd-${finding.id}`;
  const label = { good: "Good", info: "Finding", warn: "Watch", risk: "Risk" }[finding.severity] ?? "Finding";
  return (
    <div className={`ab-box is-${finding.severity}`}>
      <button type="button" className="ab-box__head" aria-expanded={open} aria-controls={bodyId} onClick={() => setOpen((v) => !v)}>
        <span className="ab-box__chev" aria-hidden="true">▶</span>
        <span className="ab-box__title">{finding.title}</span>
        <span className="ab-box__kind">{label}</span>
        {finding.gist && <span className="ab-box__gist">{finding.gist}</span>}
      </button>
      {open && (
        <div className="ab-box__body" id={bodyId}>
          {finding.details && <Markdown text={finding.details} />}
          {evidence}
        </div>
      )}
    </div>
  );
}
