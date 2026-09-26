/** Finds links in plain text, so they can be seen and opened.
 *
 * The owner: "When pasting links I would like the link to be highlighted in the
 * blue purple color so I know it works. Also I should be able to click on the
 * link I paste and take it to the site which opens in a new tab."
 *
 * Answers from Nyx already go through the markdown renderer, which makes links
 * clickable. This is for everything that is *not* markdown: what the owner
 * typed or pasted, and the text being typed in the composer.
 *
 * Only http, https and mailto become links — a bare `www.` is upgraded to
 * https. Anything else stays plain text, so a Windows path or a code fragment
 * is never turned into something clickable.
 */

import type { ReactNode } from "react";

/** http/https/mailto, and bare www. addresses. */
const LINK_RE = /((?:https?:\/\/|mailto:)[^\s<>"']+|(?<![\w@.])www\.[a-z0-9-]+(?:\.[a-z0-9-]+)+[^\s<>"']*)/gi;
/** Sentence punctuation that sits after a link rather than inside it. */
const TRAILING = /[.,;:!?)\]}'"…]+$/;

export type LinkSpan = { start: number; end: number; href: string; text: string };

/** Every link in `text`, with the exact character range it occupies. */
export function findLinks(text: string): LinkSpan[] {
  const spans: LinkSpan[] = [];
  if (!text) return spans;
  LINK_RE.lastIndex = 0;
  for (const match of text.matchAll(LINK_RE)) {
    const raw = match[0];
    const at = match.index ?? 0;
    // "(see https://x.com)" — the closing bracket belongs to the sentence,
    // unless the link opened one of its own, as Wikipedia URLs do.
    let body = raw.replace(TRAILING, (tail) => {
      const opens = (raw.match(/\(/g) ?? []).length;
      const closes = (raw.match(/\)/g) ?? []).length;
      return opens > closes && tail === ")" ? ")" : "";
    });
    if (body.length < 4) continue;
    if (body.endsWith(")") && (body.match(/\(/g) ?? []).length < (body.match(/\)/g) ?? []).length) body = body.slice(0, -1);
    spans.push({
      start: at,
      end: at + body.length,
      text: body,
      href: /^(https?:|mailto:)/i.test(body) ? body : `https://${body}`,
    });
  }
  return spans;
}

export function hasLink(text: string): boolean {
  return findLinks(text).length > 0;
}

/** Plain text with its links turned into anchors that open in a new tab. */
export function Linkified({ text }: { text: string }): ReactNode {
  const spans = findLinks(text);
  if (!spans.length) return text;
  const out: ReactNode[] = [];
  let at = 0;
  spans.forEach((span, index) => {
    if (span.start > at) out.push(text.slice(at, span.start));
    out.push(
      <a key={`${span.start}-${index}`} className="nyx-link" href={span.href} target="_blank" rel="noopener noreferrer"
         title={span.href}>
        {span.text}
      </a>,
    );
    at = span.end;
  });
  if (at < text.length) out.push(text.slice(at));
  return out;
}
