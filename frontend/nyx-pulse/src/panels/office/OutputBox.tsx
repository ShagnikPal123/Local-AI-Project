/** The Output box (Update 1, U41): only the results — the one place the office says "done".
 *
 * The owner: "the first is just what I say to main office and what they send back. Now I want a only output box, in
 * here they deliver the output needed. Links and whatnot work. This box is because sometimes the ai needs to be told
 * to output." So: each finished job's deliverable as its own card, its files open right here (they live in the
 * office's work folder, behind the owner's sign-in, so a plain link could not open them), web links open in a new
 * tab, and Deliver now makes the office hand over what it has — even halfway through a job.
 */

import { useState } from "react";
import { Markdown } from "../../components/chat/Markdown";
import { officeApi } from "./officeApi";
import type { OfficeOutput } from "./types";

const STATUS: Record<OfficeOutput["status"], string> = {
  done: "Done", partial: "So far", failed: "Not finished", stopped: "Stopped",
};

function when(ts: number): string {
  const date = new Date(ts * 1000);
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function OutputBox({ officeId, outputs, onError }: {
  officeId: string;
  outputs: OfficeOutput[];
  onError: (message: string) => void;
}) {
  const [asking, setAsking] = useState(false);
  const [file, setFile] = useState<{ path: string; text: string } | null>(null);
  const [copied, setCopied] = useState("");

  const deliver = async () => {
    setAsking(true);
    const result = await officeApi.deliver(officeId);
    setAsking(false);
    if (!result.ok) onError(result.error);
  };

  const open = async (path: string) => {
    const result = await officeApi.file(officeId, path);
    if (result.ok) setFile({ path: result.data.path, text: result.data.text });
    else onError(result.error);
  };

  const copy = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      window.setTimeout(() => setCopied(""), 1500);
    } catch { onError("Could not copy — the browser refused the clipboard."); }
  };

  const newest = [...outputs].reverse();

  return (
    <section className="ofc-chat ofc-output" aria-label="Output — what the office delivered">
      <header className="ofc-chat__head">
        <h2>Output</h2>
        <span className="ofc-chat__sub">results only</span>
        <button className="ofc-btn ofc-btn--small ofc-output__deliver" onClick={() => void deliver()} disabled={asking}
                title="Ask the office for its output now — what is finished so far, without stopping the work">
          {asking ? "Asking…" : "Deliver now"}
        </button>
      </header>
      <div className="ofc-chat__list" aria-live="polite">
        {newest.length === 0 && (
          <div className="ofc-chat__empty">
            <p className="ofc-muted">Finished work lands here: the result itself, its files and its links.</p>
            <p className="ofc-muted">Press Deliver now any time to get what the office has so far.</p>
          </div>
        )}
        {newest.map((output) => (
          <article key={output.id} className={`ofc-out is-${output.status}`}>
            <header>
              <span className={`ofc-out__status is-${output.status}`}>{STATUS[output.status] ?? output.status}</span>
              <b>{output.title}</b>
              <time dateTime={new Date(output.ts * 1000).toISOString()}>{when(output.ts)}</time>
            </header>
            <div className="ofc-out__text"><Markdown text={output.text} /></div>
            {output.links.length > 0 && (
              <ul className="ofc-out__links">
                {output.links.map((link) => (
                  <li key={`${link.kind}-${link.path ?? link.href}`}>
                    {link.kind === "file" && link.path ? (
                      <button type="button" className="ofc-chip" onClick={() => void open(link.path!)}
                              title={`Open ${link.path} from this office's work folder`}>📄 {link.label}</button>
                    ) : (
                      <a className="ofc-chip" href={link.href} target="_blank" rel="noopener noreferrer">↗ {link.label}</a>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <button type="button" className="ofc-link ofc-out__copy" onClick={() => void copy(output.id, output.text)}>
              {copied === output.id ? "Copied" : "Copy"}
            </button>
          </article>
        ))}
      </div>
      {file && (
        <div className="ofc-file" role="dialog" aria-label={`File ${file.path}`}>
          <header>
            <b>{file.path}</b>
            <button type="button" className="ofc-link" onClick={() => void copy(`file:${file.path}`, file.text)}>
              {copied === `file:${file.path}` ? "Copied" : "Copy"}
            </button>
            <button type="button" className="ofc-icon" onClick={() => setFile(null)} aria-label="Close the file">✕</button>
          </header>
          <pre>{file.text}</pre>
        </div>
      )}
    </section>
  );
}
