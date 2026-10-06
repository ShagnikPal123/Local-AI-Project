/** One message: the assistant's whole turn, or a user's words.
 *
 * Everything the turn produced is visible here, progressively disclosed so a
 * long turn reads top-down in the order it happened: status → what Nyx is
 * thinking → which agents joined → each tool step → the answer. Nothing is
 * colour-only; every collapsed section has a real heading with a count.
 */

import { useState } from "react";
import type { ChatMessageView, MessageBubbleProps, OptimizedRequest, SourceLink } from "./types";
import { api } from "../../api";
import { Markdown } from "./Markdown";
import { copyToClipboard } from "./hooks";
import { formatDuration, safeImageSrc } from "./format";
import { AgentDisc, Spinner } from "./AgentDisc";
import { Icon } from "./Icon";
import { onSpeakingChange, speakText, stopSpeaking } from "../../voice/voicePlayer";
import { Linkified } from "./linkify";
import { Handoff } from "../agents/Handoff";
import { MODE_LABELS, type ChatMode } from "./ModeSlider";

const cardStyle: React.CSSProperties = {
  background: "var(--color-surface)",
  borderRadius: "var(--radius)",
  padding: "10px 14px",
  boxShadow: "inset 0 0 0 1px var(--color-divider)",
  lineHeight: 1.6,
  fontSize: 14,
};

const metaStyle: React.CSSProperties = {
  marginTop: 8,
  fontSize: 11,
  color: "var(--color-neutral-600)",
  fontFamily: "var(--font-mono)",
};

/** Where the answer came from (Request H15): a disclosure with real links that open in a new tab. */
function SourcesMenu({ sources }: { sources: SourceLink[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="sources">
      <button className="chat-collapse sources__toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <Icon name={open ? "chevronDown" : "chevronRight"} size={12} />
        Sources
        <span className="sources__count">({sources.length})</span>
        {!open && (
          <span className="sources__peek" aria-hidden="true">
            {sources.slice(0, 3).map((s) => s.domain).join(" · ")}
          </span>
        )}
      </button>
      {open && (
        <ol className="sources__list">
          {sources.map((source, index) => (
            <li key={source.url}>
              <a href={source.url} target="_blank" rel="noopener noreferrer" className="sources__link"
                title={source.url} aria-label={`${source.title} — ${source.domain} (opens in a new tab)`}>
                <span className="sources__badge" aria-hidden="true">{index + 1}</span>
                <span className="sources__text">
                  <span className="sources__title">{source.title}</span>
                  <span className="sources__domain">{source.domain} ↗</span>
                </span>
              </a>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Collapsible({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="chat-collapse"
      >
        <Icon name={open ? "chevronDown" : "chevronRight"} size={12} />
        {title}
        {typeof count === "number" && count > 0 && (
          <span style={{ color: "var(--color-neutral-500)", fontWeight: 400 }}>({count})</span>
        )}
      </button>
      {open && <div style={{ marginTop: 6 }}>{children}</div>}
    </div>
  );
}

function OptimizedNote({ optimized }: { optimized: OptimizedRequest }) {
  const [open, setOpen] = useState(false);
  const [off, setOff] = useState(false);
  const verb = optimized.mode === "polish" ? "Structured" : "Expanded";
  return (
    <div className="optimized-note">
      <button className="optimized-note__head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <Icon name={open ? "chevronDown" : "chevronRight"} size={12} />
        <span>{verb} your request for the model</span>
        <span className="optimized-note__meta">
          {optimized.engine === "rules" ? "offline rules" : optimized.engine} · {optimized.ms} ms
        </span>
      </button>
      {open && (
        <div className="optimized-note__body">
          <div className="optimized-note__label">You wrote</div>
          <div className="optimized-note__text">{optimized.original}</div>
          <div className="optimized-note__label">Nyx also gave the model</div>
          <div className="optimized-note__text is-refined">{optimized.optimized}</div>
          {optimized.assumptions.length > 0 && (
            <div className="optimized-note__assume">Assumed: {optimized.assumptions.join(" · ")}</div>
          )}
          <div className="optimized-note__foot">
            Your own words always went first, and win if the two ever disagree.
            {!off ? (
              <button className="chat-inline" onClick={async () => {
                const result = await api.put("/api/optimizer/settings", { enabled: false });
                if (result.ok) setOff(true);
              }}>Stop refining my requests</button>
            ) : <span> Refining is off — turn it back on in Settings.</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function ToolStepRow({ step }: { step: NonNullable<ChatMessageView["turn"]>["steps"][number] }) {
  const [open, setOpen] = useState(false);
  const expandable = step.progress.length > 0 || !!step.preview || step.images.length > 0;
  return (
    <li style={{ listStyle: "none", padding: "5px 0", boxShadow: "inset 0 -1px 0 var(--color-divider)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
        {step.status === "running" ? (
          <Spinner />
        ) : (
          <Icon name={step.status === "error" ? "close" : "check"} size={13} />
        )}
        <span style={{ flex: 1, minWidth: 0 }}>{step.label}</span>
        {step.agent && <span style={{ fontSize: 11, color: "var(--color-neutral-600)" }}>via {step.agent}</span>}
        {step.ms !== undefined && (
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-neutral-600)" }}>
            {formatDuration(step.ms)}
          </span>
        )}
        {expandable && (
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="chat-inline"
          >
            {open ? "Hide" : "Details"}
          </button>
        )}
      </div>
      {open && (
        <div style={{ marginTop: 6, fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
          {step.progress.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
          {step.preview && <div style={{ fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap" }}>{step.preview}</div>}
          {step.images.map((image, i) => (
            <img
              key={i}
              src={safeImageSrc(image.dataUrl) ?? image.dataUrl}
              alt={image.note || image.name || "Tool image"}
              style={{ maxWidth: "100%", borderRadius: "var(--radius)", marginTop: 6 }}
            />
          ))}
        </div>
      )}
    </li>
  );
}

function AgentRow({ agent }: { agent: NonNullable<ChatMessageView["turn"]>["agents"][number] }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "5px 0", fontSize: 12 }}>
      <AgentDisc name={agent.name} emoji={agent.emoji} color={agent.color} status={agent.status === "working" ? "working" : agent.status === "error" ? "error" : "done"} size="sm" />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div>
          <span style={{ fontWeight: 600 }}>{agent.name}</span>
          {agent.created && (
            <span style={{
              fontSize: 11, marginLeft: 6, color: "var(--color-accent)",
              border: "1px solid var(--color-accent)", borderRadius: 4, padding: "0 4px",
            }}>
              new
            </span>
          )}
          <span style={{ color: "var(--color-neutral-600)", marginLeft: 6 }}>
            {agent.status === "working" ? agent.step || "working" : agent.status === "error" ? "hit a problem" : "done"}
          </span>
        </div>
        {agent.understanding && (
          <div style={{ color: "var(--color-neutral-500)", marginTop: 2 }}>{agent.understanding}</div>
        )}
        {/* What it was asked and what it answered, in full (U46). An older engine sent only a preview. */}
        {agent.task || agent.report ? (
          <Handoff task={agent.task} context={agent.context} report={agent.report || agent.resultPreview}
            working={agent.status === "working"} />
        ) : agent.resultPreview && (
          <div style={{ color: "var(--color-neutral-600)", marginTop: 2, whiteSpace: "pre-wrap" }}>
            {agent.resultPreview}
          </div>
        )}
      </div>
    </div>
  );
}

export function MessageBubble({ message, onAction, isLatest = false }: MessageBubbleProps) {
  const turn = message.turn;
  const streaming = turn?.state === "streaming";
  const [copied, setCopied] = useState(false);
  const [listening, setListening] = useState<"idle" | "loading" | "playing" | "error">("idle");

  if (message.role === "user") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <div
          style={{
            ...cardStyle,
            maxWidth: "78%",
            background: "var(--color-accent-900)",
            whiteSpace: "pre-wrap",
          }}
        >
          <Linkified text={message.content} />
          {message.attachments && message.attachments.length > 0 && (
            <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {message.attachments.map((a) => (
                <span key={a.id} style={{ fontSize: 11, color: "var(--color-neutral-500)" }}>
                  {a.kind === "image" ? "🖼" : "📄"} {a.name}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  const thoughts = turn?.thoughts ?? [];
  const agents = turn?.agents ?? [];
  const steps = turn?.steps ?? [];
  const skillsUsed = turn?.skillsUsed ?? [];
  const skillsCreated = turn?.skillsCreated ?? [];
  const approvals = turn?.approvals ?? [];
  const learningNotes = turn?.learningNotes ?? [];

  return (
    <div style={{ display: "flex", justifyContent: "flex-start" }}>
      <div
        style={{
          ...cardStyle,
          maxWidth: "86%",
          borderLeft: message.role === "error" ? "3px solid var(--color-danger)" : undefined,
        }}
      >
        {/* Live status while the turn runs: never a bare spinner. */}
        {streaming && turn?.status && (
          <div
            aria-live="polite"
            style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--color-neutral-400)", marginBottom: 6 }}
          >
            <Spinner />
            <span>{turn.status}</span>
          </div>
        )}

        {/* The slider was on Auto: which mode it picked for this message, and why (Update 1, U6). */}
        {turn?.chatModeAuto && turn.chatMode && (
          <p className="turn-mode">
            Auto picked <b>{MODE_LABELS[turn.chatMode as ChatMode]?.name ?? turn.chatMode}</b>
            {turn.chatModeReason ? <span>· {turn.chatModeReason}</span> : null}
          </p>
        )}

        {/* /auto or @auto: the team Auto put together for this job (Update 1, U21). */}
        {turn?.autoTeam && (
          <p className="turn-mode">
            <b>Auto team</b>
            <span>
              {[
                turn.autoTeam.skills.length ? `skills ${turn.autoTeam.skills.map((s) => s.name).join(", ")}` : "",
                turn.autoTeam.agents.length ? `agents ${turn.autoTeam.agents.map((a) => `${a.emoji ? `${a.emoji} ` : ""}${a.name}`).join(", ")}`
                  : turn.autoTeam.createAgent ? "a new agent made for this job" : "",
                turn.autoTeam.connectors.length ? `connectors ${turn.autoTeam.connectors.map((c) => c.name).join(", ")}` : "",
              ].filter(Boolean).join(" · ") || "no team needed — a quick job"}
            </span>
          </p>
        )}

        {/* Prompt optimizer disclosure (generative-ai.md: say where AI is used, keep people in control). */}
        {turn?.optimized && <OptimizedNote optimized={turn.optimized} />}

        {/* What a Co-work turn is made of, and how far it has got (chat_modes.update_checklist). */}
        {turn?.checklist && turn.checklist.length > 0 && (
          <ul className="work-checklist" aria-label="What it is working through">
            {turn.checklist.map((item, i) => (
              <li key={i} className={`is-${item.status}`}>
                <span className="work-checklist__mark" aria-hidden="true">
                  {item.status === "done" ? "✓" : item.status === "doing" ? "▸" : item.status === "blocked" ? "!" : item.status === "skipped" ? "–" : "○"}
                </span>
                <span>{item.text}</span>
                {item.status === "doing" && <em>working…</em>}
                {item.status === "blocked" && <em>blocked</em>}
              </li>
            ))}
          </ul>
        )}

        {thoughts.length > 0 && (
          <Collapsible title="Thinking" count={thoughts.length} defaultOpen={Boolean(streaming && isLatest)}>
            {thoughts.map((chunk, i) => (
              <div key={i} style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6, marginBottom: 6 }}>
                {chunk.agent && <div style={{ fontWeight: 600, color: "var(--color-neutral-400)" }}>{chunk.agent}</div>}
                {chunk.text}
              </div>
            ))}
          </Collapsible>
        )}

        {agents.length > 0 && (
          <Collapsible title="Agents" count={agents.length} defaultOpen={Boolean(streaming && isLatest)}>
            {agents.map((agent) => (
              <AgentRow key={agent.callId ?? agent.agentId} agent={agent} />
            ))}
          </Collapsible>
        )}

        {steps.length > 0 && (
          <Collapsible title="Steps" count={steps.length} defaultOpen={Boolean(streaming && isLatest)}>
            <ul style={{ margin: 0, padding: 0 }}>
              {steps.map((step) => (
                <ToolStepRow key={step.callId} step={step} />
              ))}
            </ul>
          </Collapsible>
        )}

        {(skillsUsed.length > 0 || skillsCreated.length > 0) && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
            {skillsUsed.map((skill) => (
              <span key={skill.id} style={{ fontSize: 11, padding: "2px 8px", borderRadius: 999, boxShadow: "inset 0 0 0 1px var(--color-divider)", color: "var(--color-neutral-400)" }}>
                ⚡ {skill.name}
              </span>
            ))}
            {skillsCreated.map((skill) => (
              <span key={skill.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, padding: "2px 8px", borderRadius: 999, boxShadow: "inset 0 0 0 1px var(--color-accent)", color: "var(--color-accent)" }}>
                built “{skill.name}” for this
                <button
                  onClick={() => onAction({ type: "keepSkill", skillId: skill.id })}
                  className="chat-inline"
                >
                  keep
                </button>
              </span>
            ))}
          </div>
        )}

        {approvals.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {approvals.map((approval) => (
              <div
                key={approval.id}
                style={{
                  padding: "8px 10px", borderRadius: "var(--radius)",
                  boxShadow: "inset 0 0 0 1px var(--color-warn)", fontSize: 12, lineHeight: 1.5,
                }}
              >
                <div style={{ fontWeight: 600 }}>{approval.summary}</div>
                {approval.detail && <div style={{ color: "var(--color-neutral-500)", marginTop: 2 }}>{approval.detail}</div>}
                {!approval.resolved ? (
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    <button className="btn btn-primary" style={{ fontSize: 12, padding: "4px 12px" }}
                      onClick={() => onAction({ type: "approve", approvalId: approval.id, approve: true })}>
                      Allow
                    </button>
                    <button className="btn btn-secondary" style={{ fontSize: 12, padding: "4px 12px" }}
                      onClick={() => onAction({ type: "approve", approvalId: approval.id, approve: false })}>
                      Deny
                    </button>
                  </div>
                ) : (
                  <div style={{ marginTop: 6, color: "var(--color-neutral-600)" }}>
                    {approval.approved ? "Allowed." : "Denied."}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Which assigned model did which job — the owner asked that both he and
            Nyx say it. One chip per use, with the fallback reason when the
            assigned model could not do it. */}
        {(turn?.models ?? []).length > 0 && (
          <div className="chat-models" aria-label="Models used">
            {(turn?.models ?? []).map((use, i) => (
              <span key={`${use.role}-${i}`} className={`chat-model-chip${use.fellBack ? " is-fallback" : ""}`}
                title={use.note ? `${use.provider}/${use.model} — ${use.note}` : `${use.provider}/${use.model}`}>
                <strong>{use.label}</strong> · {use.title.toLowerCase()}
                {typeof use.ms === "number" && ` · ${(use.ms / 1000).toFixed(1)}s`}
                {use.fellBack && " · fallback"}
              </span>
            ))}
          </div>
        )}

        {/* Pictures Nyx made belong with the answer, not buried in the steps. */}
        {steps.some((s) => s.images.some((image) => image.generated)) && (
          <div className="chat-generated">
            {steps.flatMap((s) => s.images.filter((image) => image.generated)).map((image, i) => {
              const src = image.uploadId ? `/api/uploads/${image.uploadId}` : image.dataUrl;
              return (
                <button key={`${image.uploadId ?? i}`} className="chat-generated__item"
                  onClick={() => onAction({ type: "openImage", src })} title={image.note || image.name}>
                  <img src={src} alt={image.name || "Generated image"} loading="lazy"
                    onError={(e) => { if (image.dataUrl && e.currentTarget.src !== image.dataUrl) e.currentTarget.src = image.dataUrl; }} />
                  {image.note && <span>{image.note}</span>}
                </button>
              );
            })}
          </div>
        )}

        {/* The answer. Markdown renders progressively while streaming. */}
        <Markdown text={turn ? turn.answer || message.content : message.content} streaming={streaming} />

        {!streaming && (turn?.sources ?? message.sources ?? []).length > 0 && (
          <SourcesMenu sources={(turn?.sources ?? message.sources)!} />
        )}

        {turn?.cached && (
          <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 6 }}>
            Answered from cache{typeof turn.cached.similarity === "number" ? ` (${Math.round(turn.cached.similarity * 100)}% match)` : ""}.{" "}
            <button
              onClick={() => onAction({ type: "refreshCached", messageId: message.id })}
              className="chat-inline"
            >
              Answer fresh instead
            </button>
          </div>
        )}

        {learningNotes.map((note, i) => (
          <div key={i} style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 6 }}>🧠 {note}</div>
        ))}

        {(turn?.provider || turn?.elapsedMs !== undefined || message.provider) && (
          <div style={metaStyle}>
            {turn?.provider ?? message.provider ?? "error"}
            {turn?.model ? ` · ${turn.model}` : ""}
            {(turn?.elapsedMs ?? message.provider) !== undefined && turn?.elapsedMs !== undefined && ` · ${formatDuration(turn.elapsedMs)}`}
          </div>
        )}

        {/* Actions: only for finished turns, only what works. */}
        {!streaming && message.role === "assistant" && (
          <div className="chat-actions">
            <button
              className="chat-action"
              title="Copy the answer"
              onClick={async () => {
                const ok = await copyToClipboard(turn?.answer || message.content);
                if (ok) {
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1500);
                }
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              className="chat-action"
              title="Branch from here — a new chat with the conversation up to this answer"
              onClick={() => onAction({ type: "branch", messageId: message.id })}
            >
              Branch
            </button>
            <button
              className="chat-action"
              title={listening === "error" ? "Could not play — the neural voices need internet" : "Read this answer aloud"}
              aria-pressed={listening === "playing"}
              onClick={async () => {
                if (listening === "playing") { stopSpeaking(); setListening("idle"); return; }
                setListening("loading");
                try {
                  await speakText(turn?.answer || message.content, { role: "reply" });
                  setListening("playing");
                  const off = onSpeakingChange((speaking) => { if (speaking === null) { setListening("idle"); off(); } });
                } catch {
                  setListening("error");
                }
              }}
            >
              {listening === "loading" ? "Voicing…" : listening === "playing" ? "Stop" : listening === "error" ? "Voice failed" : "Listen"}
            </button>
            {turn?.turnId && (
              <>
                <button
                  className="chat-action"
                  title="Good answer — Nyx learns from this"
                  aria-label="Good answer"
                  onClick={() => onAction({ type: "feedback", messageId: message.id, turnId: turn.turnId, value: 1 })}
                >
                  👍
                </button>
                <button
                  className="chat-action"
                  title="Bad answer — Nyx learns from this, and the cache is cleared"
                  aria-label="Bad answer"
                  onClick={() => onAction({ type: "feedback", messageId: message.id, turnId: turn.turnId, value: -1 })}
                >
                  👎
                </button>
                <button
                  className="chat-action"
                  title="Say this answer aloud"
                  onClick={() => onAction({ type: "speak", messageId: message.id })}
                >
                  Speak
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
