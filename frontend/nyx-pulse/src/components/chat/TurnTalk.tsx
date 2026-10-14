/** What Nyx says to the owner while it works (active_speech.py): the same lines a voice turn reads aloud.
 *
 * Before the answer: what it understood, what it is doing, and its reply to anything sent mid-task.
 * After the answer: the one-line wrap-up of a longer turn.
 */

import type { SpeechLine } from "./types";

const MODE_WORDS: Record<string, string> = {
  fold: "added to this task",
  queue: "next in line",
  interrupt: "goes now",
  parallel: "running alongside",
  branch: "own branch",
};

export function TurnTalk({ lines, part }: { lines?: SpeechLine[]; part: "before" | "after" }) {
  const shown = (lines ?? []).filter((line) => (part === "after" ? line.phase === "end" : line.phase !== "end"));
  if (shown.length === 0) return null;
  return (
    <div className={`turn-talk turn-talk--${part}`} aria-live="polite">
      {shown.map((line, i) => (
        <p key={`${line.phase}-${i}`} className={`turn-talk__line is-${line.phase}`}>
          <span className="turn-talk__mark" aria-hidden="true">
            {line.phase === "start" ? "●" : line.phase === "heard" ? "↳" : line.phase === "end" ? "✓" : "·"}
          </span>
          <span>
            {line.phase === "heard" && line.note && (
              <span className="turn-talk__note">
                You: “{line.note.length > 80 ? `${line.note.slice(0, 80)}…` : line.note}”
                {line.mode && MODE_WORDS[line.mode] ? <em> · {MODE_WORDS[line.mode]}</em> : null}
              </span>
            )}
            {line.text}
          </span>
        </p>
      ))}
    </div>
  );
}
