/** The plan Nyx wrote, for you to check before anything happens (Project Null N84).
 *
 * "Basically a better confirm": instead of a yes/no dialog over work you cannot
 * see, you get the spec it intends to meet, the steps it would take, what it is
 * assuming, and the questions it needs answered — and you can strike out lines,
 * answer the questions and add your own before pressing Approve. Approving sends
 * the plan back as the next message; only that turn is allowed to change anything.
 */

import { useState } from "react";

interface Step { title: string; detail?: string; minutes?: number }
interface Question { question: string; options?: { label: string; means?: string; recommended?: boolean }[]; multi?: boolean }
interface Plan {
  goal: string;
  spec: string[];
  steps: Step[];
  questions: Question[];
  risks: string[];
  assumptions: string[];
}

function parse(source: string): Plan | null {
  try {
    const data = JSON.parse(source) as Record<string, unknown>;
    const list = (value: unknown): string[] => Array.isArray(value) ? value.map((v) => String(v)).filter(Boolean) : [];
    const steps: Step[] = Array.isArray(data.steps)
      ? (data.steps as unknown[]).map((raw) => typeof raw === "string"
          ? { title: raw }
          : { title: String((raw as Step).title ?? ""), detail: String((raw as Step).detail ?? ""), minutes: Number((raw as Step).minutes) || undefined })
        .filter((step) => step.title)
      : [];
    const questions: Question[] = Array.isArray(data.questions)
      ? (data.questions as Question[]).filter((q) => q && String(q.question ?? "").trim()).slice(0, 4)
      : [];
    const goal = String(data.goal ?? data.title ?? "").trim();
    const spec = list(data.spec ?? data.specs ?? data.requirements);
    if (!goal && !spec.length && !steps.length) return null;
    return { goal, spec, steps, questions, risks: list(data.risks), assumptions: list(data.assumptions) };
  } catch {
    return null;
  }
}

export function PlanCard({ source }: { source: string }) {
  const plan = parse(source);
  const [dropped, setDropped] = useState<Set<number>>(new Set());
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [extra, setExtra] = useState("");
  const [sent, setSent] = useState(false);

  if (!plan) return null;

  const toggleSpec = (index: number) => {
    setDropped((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index); else next.add(index);
      return next;
    });
  };

  const approve = () => {
    const kept = plan.spec.filter((_, index) => !dropped.has(index));
    const lines = ["[Plan approved — do it now]", plan.goal ? `Goal: ${plan.goal}` : ""];
    if (kept.length) lines.push("What it must do:", ...kept.map((item) => `- ${item}`));
    const removed = plan.spec.filter((_, index) => dropped.has(index));
    if (removed.length) lines.push("Dropped (do NOT do these):", ...removed.map((item) => `- ${item}`));
    if (plan.steps.length) lines.push("Steps:", ...plan.steps.map((step, i) => `${i + 1}. ${step.title}${step.detail ? ` — ${step.detail}` : ""}`));
    const answered = plan.questions.map((question, index) => [question.question, answers[index]] as const).filter(([, value]) => value && value.trim());
    if (answered.length) lines.push("My answers:", ...answered.map(([question, value]) => `- ${question} → ${value}`));
    if (extra.trim()) lines.push("Also:", extra.trim());
    setSent(true);
    window.dispatchEvent(new CustomEvent("nyx:chat-send", { detail: { text: lines.filter(Boolean).join("\n"), mode: "plan_go" } }));
  };

  const totalMinutes = plan.steps.reduce((sum, step) => sum + (step.minutes ?? 0), 0);

  return (
    <section className={`plan-card${sent ? " is-sent" : ""}`} aria-label="The plan, for you to check">
      <header>
        <span className="plan-card__tag">Plan — nothing has happened yet</span>
        {plan.goal && <h3>{plan.goal}</h3>}
        {totalMinutes > 0 && <span className="plan-card__time">about {totalMinutes} min of work</span>}
      </header>

      {plan.spec.length > 0 && (
        <div className="plan-card__block">
          <h4>What it must do</h4>
          <ul className="plan-card__spec">
            {plan.spec.map((item, index) => (
              <li key={index} className={dropped.has(index) ? "is-dropped" : ""}>
                <label>
                  <input type="checkbox" checked={!dropped.has(index)} disabled={sent} onChange={() => toggleSpec(index)} />
                  <span>{item}</span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}

      {plan.steps.length > 0 && (
        <div className="plan-card__block">
          <h4>How</h4>
          <ol className="plan-card__steps">
            {plan.steps.map((step, index) => (
              <li key={index}>
                <b>{step.title}</b>
                {step.detail && <span>{step.detail}</span>}
                {step.minutes ? <em>{step.minutes} min</em> : null}
              </li>
            ))}
          </ol>
        </div>
      )}

      {(plan.assumptions.length > 0 || plan.risks.length > 0) && (
        <div className="plan-card__block plan-card__aside">
          {plan.assumptions.length > 0 && (
            <div><h4>Taking as given</h4><ul>{plan.assumptions.map((item, i) => <li key={i}>{item}</li>)}</ul></div>
          )}
          {plan.risks.length > 0 && (
            <div><h4>Could go wrong</h4><ul>{plan.risks.map((item, i) => <li key={i}>{item}</li>)}</ul></div>
          )}
        </div>
      )}

      {plan.questions.length > 0 && !sent && (
        <div className="plan-card__block">
          <h4>It needs you to decide</h4>
          {plan.questions.map((question, index) => (
            <div key={index} className="plan-card__question">
              <p>{question.question}</p>
              <div className="plan-card__answers">
                {(question.options ?? []).map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    className={`plan-card__answer${answers[index] === option.label ? " is-chosen" : ""}`}
                    aria-pressed={answers[index] === option.label}
                    onClick={() => setAnswers((current) => ({ ...current, [index]: option.label }))}
                  >
                    <b>{option.label}{option.recommended && <span className="q-card__tag">would pick</span>}</b>
                    {option.means && <span>{option.means}</span>}
                  </button>
                ))}
              </div>
              <input
                className="plan-card__own"
                value={answers[index] && !(question.options ?? []).some((o) => o.label === answers[index]) ? answers[index] : ""}
                onChange={(event) => setAnswers((current) => ({ ...current, [index]: event.target.value }))}
                placeholder="Or your own answer"
                aria-label={`Your own answer to: ${question.question}`}
              />
            </div>
          ))}
        </div>
      )}

      {!sent && (
        <div className="plan-card__approve">
          <textarea
            value={extra}
            onChange={(event) => setExtra(event.target.value)}
            placeholder="Anything to add or change before it starts?"
            aria-label="Anything to add to the plan"
            rows={2}
          />
          <button type="button" className="nyx-btn nyx-btn--primary" onClick={approve}>Approve and Start</button>
          <span className="plan-card__hint">Unticked lines are dropped. Nothing runs until you press this.</span>
        </div>
      )}
      {sent && <p className="plan-card__hint">Approved — it is working through the plan now.</p>}
    </section>
  );
}
