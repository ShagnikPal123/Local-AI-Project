/** What a sub-agent was asked, and what it answered (Update 1, U46).
 *
 * The owner: "when the auto asks an sub agent to do something we the user can see
 * what is asked as well as what they responded with". So every hand-off — one
 * agent from the chat, a box in a dispatch, a copy in a swarm — shows the request
 * exactly as it was sent (the task and the context the agent was given; it never
 * sees the chat itself) and the reply exactly as it came back. Both start folded
 * to one line so a swarm of twenty stays readable, and open on a click.
 */

import { Linkified } from "../chat/linkify";
import "./handoff.css";

function firstLine(text: string): string {
  return text.trim().split("\n").find((line) => line.trim()) ?? "";
}

export function Handoff({ task, context, report, working, replyOpen = false }: {
  task?: string;
  /** Everything else the agent was handed with the task: shared facts, the project, its sibling copies. */
  context?: string;
  report?: string;
  /** Still working: say a reply is coming rather than showing nothing. */
  working?: boolean;
  /** Open the reply straight away (when the owner has just clicked into this agent). */
  replyOpen?: boolean;
}) {
  if (!task && !report) return null;
  return (
    <div className="handoff">
      {task && (
        <details>
          <summary><b>Asked</b><span>{firstLine(task)}</span></summary>
          <div className="handoff__body">
            {task.trim()}
            {context?.trim() && (
              <>
                <span className="handoff__label">With this context</span>
                {context.trim()}
              </>
            )}
          </div>
        </details>
      )}
      {report ? (
        <details open={replyOpen}>
          <summary><b>Replied</b><span>{firstLine(report)}</span></summary>
          <div className="handoff__body"><Linkified text={report.trim()} /></div>
        </details>
      ) : working ? (
        <p className="handoff__waiting" aria-live="polite">Working on it — the reply shows here when it comes back.</p>
      ) : null}
    </div>
  );
}
