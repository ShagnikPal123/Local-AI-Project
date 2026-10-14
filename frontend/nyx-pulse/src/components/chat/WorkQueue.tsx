/** The visible queue: what Nyx is doing now, and every message waiting behind it with Nyx's reply to it.
 *
 * Active speech (2026-10-14): a message sent mid-task is answered at once ("Got it — next, I'll …"), and that
 * answer stays next to the message here until it goes, so the owner can see how the work was split up.
 */

export interface QueuedItem {
  id: string;
  text: string;
  attachmentIds: string[];
  /** queue | interrupt (goes first) — what was decided for it. */
  mode?: string;
  /** What Nyx said when it arrived. */
  ack?: string;
}

export function WorkQueue({ items, now, onRemove }: {
  items: QueuedItem[];
  /** What the running turn is doing, in words. */
  now?: string;
  onRemove: (id: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="work-queue" aria-live="polite" aria-label="Waiting to be sent">
      {now && (
        <div className="work-queue__now">
          <span className="work-queue__dot" aria-hidden="true" />Working on it now · {now}
        </div>
      )}
      <ol className="work-queue__list">
        {items.map((item, i) => (
          <li key={item.id} className="work-queue__item">
            <span className="work-queue__pos">{item.mode === "interrupt" && i === 0 ? "now" : i + 1}</span>
            <span className="work-queue__body">
              <span className="work-queue__text" title={item.text}>
                {item.text.length > 90 ? `${item.text.slice(0, 90)}…` : item.text}
              </span>
              {item.ack && <span className="work-queue__ack">{item.ack}</span>}
            </span>
            <button className="work-queue__remove" aria-label="Remove from the queue" onClick={() => onRemove(item.id)}>✕</button>
          </li>
        ))}
      </ol>
    </div>
  );
}
