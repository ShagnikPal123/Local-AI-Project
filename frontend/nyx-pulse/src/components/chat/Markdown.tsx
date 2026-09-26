/** A small, safe Markdown renderer.
 *
 * Builds React elements directly — there is no HTML string anywhere, so model
 * output can never inject markup or script. Raw HTML in the source renders as
 * literal text. Links are limited to http/https/mailto and always open in a new
 * tab without an opener; images render only from local sources (data:, blob:,
 * same-origin paths) so a reply cannot make the browser fetch a remote tracker.
 *
 * Supported: ATX headings, paragraphs (single newlines are line breaks, as chat
 * users expect), **bold** / __bold__, *italic* / _italic_, ~~strike~~, `code`,
 * fenced code blocks (language label + Copy), ordered/unordered lists with one
 * nesting level and task boxes, blockquotes, pipe tables, horizontal rules,
 * links, autolinks and bare URLs.
 *
 * While `streaming`, an unclosed fence renders as an open code block and a caret
 * sits at the end of the last block.
 */

import { Fragment, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { MarkdownProps } from "./types";
import { copyToClipboard } from "./hooks";
import { safeHref, safeImageSrc } from "./format";
import { Icon } from "./Icon";
import { ChartBox } from "./ChartBox";
import { PlanCard } from "./PlanCard";
import { PythonBox } from "./PythonBox";
import { findCardJson, QuestionCard } from "./QuestionCard";

// ---------------------------------------------------------------------------
// Block model
// ---------------------------------------------------------------------------

type Align = "left" | "center" | "right" | undefined;

interface ListModel {
  ordered: boolean;
  start: number;
  items: ListItem[];
}

interface ListItem {
  text: string;
  checked?: boolean;
  children?: ListModel;
}

type Block =
  | { t: "p"; text: string }
  | { t: "h"; level: number; text: string }
  | { t: "code"; lang: string; code: string; open: boolean }
  | { t: "hr" }
  | { t: "quote"; blocks: Block[] }
  | { t: "list"; list: ListModel }
  | { t: "table"; align: Align[]; head: string[]; rows: string[][] };

const FENCE = /^( {0,3})(`{3,}|~{3,})[ \t]*([^\s`]*)[^`]*$/;
const HEADING = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$/;
const HR = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const QUOTE = /^ {0,3}>[ \t]?(.*)$/;
const LIST = /^( *)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/;
const TABLE_SEP = /^[ \t]*\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$/;
const TASK = /^\[([ xX])\][ \t]+(.*)$/;

function isBlank(line: string): boolean {
  return line.trim() === "";
}

function isTableStart(lines: string[], i: number): boolean {
  const head = lines[i];
  const sep = lines[i + 1];
  return sep !== undefined && head.includes("|") && sep.includes("|") && TABLE_SEP.test(sep);
}

/** Lines that end a paragraph because they begin another block. */
function startsBlock(lines: string[], i: number): boolean {
  const line = lines[i];
  if (FENCE.test(line) || HEADING.test(line) || HR.test(line) || QUOTE.test(line)) return true;
  const m = LIST.exec(line);
  // Only "1." may interrupt a paragraph, so "2024. was a year" stays prose.
  if (m && (!/\d/.test(m[2]) || /^1[.)]$/.test(m[2]))) return true;
  return isTableStart(lines, i);
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

function makeItem(raw: string): ListItem {
  const task = TASK.exec(raw);
  if (task) return { text: task[2], checked: task[1] !== " " };
  return { text: raw };
}

function parseList(lines: string[], start: number): [ListModel, number] {
  const first = LIST.exec(lines[start])!;
  const baseIndent = first[1].length;
  const ordered = /\d/.test(first[2]);
  const list: ListModel = { ordered, start: ordered ? parseInt(first[2], 10) || 1 : 1, items: [] };
  let i = start;
  while (i < lines.length) {
    const line = lines[i];
    if (isBlank(line)) {
      let j = i + 1;
      while (j < lines.length && isBlank(lines[j])) j++;
      const next = j < lines.length ? LIST.exec(lines[j]) : null;
      if (next && next[1].length >= baseIndent && (next[1].length > baseIndent + 1 || /\d/.test(next[2]) === ordered)) {
        i = j;
        continue;
      }
      break;
    }
    const m = LIST.exec(line);
    if (m) {
      const indent = m[1].length;
      const itemOrdered = /\d/.test(m[2]);
      if (indent <= baseIndent + 1 || list.items.length === 0) {
        if (itemOrdered !== ordered) break;
        list.items.push(makeItem(m[3]));
      } else {
        // One nesting level: anything deeper flattens into it.
        const parent = list.items[list.items.length - 1];
        if (!parent.children) {
          parent.children = { ordered: itemOrdered, start: itemOrdered ? parseInt(m[2], 10) || 1 : 1, items: [] };
        }
        parent.children.items.push(makeItem(m[3]));
      }
      i++;
      continue;
    }
    // Continuation text for the last item (indented, or lazy prose that starts no block).
    if (FENCE.test(line) || HEADING.test(line) || HR.test(line) || QUOTE.test(line) || isTableStart(lines, i)) break;
    const parent = list.items[list.items.length - 1];
    const target = parent.children ? parent.children.items[parent.children.items.length - 1] : parent;
    target.text += `\n${line.trim()}`;
    i++;
  }
  return [list, i];
}

function parseBlocks(src: string, depth = 0): Block[] {
  const lines = src.split("\n").map((l) => l.replace(/^\t+/, (tabs) => "    ".repeat(tabs.length)));
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (isBlank(line)) {
      i++;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      const indent = fence[1].length;
      const marker = fence[2];
      const closer = new RegExp(`^ {0,3}${marker[0] === "`" ? "`" : "~"}{${marker.length},}[ \\t]*$`);
      const body: string[] = [];
      let j = i + 1;
      let closed = false;
      while (j < lines.length) {
        if (closer.test(lines[j])) {
          closed = true;
          break;
        }
        body.push(indent ? lines[j].replace(new RegExp(`^ {0,${indent}}`), "") : lines[j]);
        j++;
      }
      blocks.push({ t: "code", lang: fence[3] ?? "", code: body.join("\n"), open: !closed });
      i = closed ? j + 1 : j;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ t: "h", level: heading[1].length, text: heading[2] ?? "" });
      i++;
      continue;
    }

    if (HR.test(line)) {
      blocks.push({ t: "hr" });
      i++;
      continue;
    }

    if (QUOTE.test(line)) {
      const inner: string[] = [];
      while (i < lines.length && QUOTE.test(lines[i])) {
        inner.push(QUOTE.exec(lines[i])![1]);
        i++;
      }
      blocks.push(depth < 3 ? { t: "quote", blocks: parseBlocks(inner.join("\n"), depth + 1) } : { t: "p", text: inner.join("\n") });
      continue;
    }

    if (isTableStart(lines, i)) {
      const head = splitRow(line);
      const align: Align[] = splitRow(lines[i + 1]).map((cell) => {
        const left = cell.startsWith(":");
        const right = cell.endsWith(":");
        return left && right ? "center" : right ? "right" : left ? "left" : undefined;
      });
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && !isBlank(lines[i]) && lines[i].includes("|")) {
        const cells = splitRow(lines[i]);
        rows.push(head.map((_, c) => cells[c] ?? ""));
        i++;
      }
      blocks.push({ t: "table", align: head.map((_, c) => align[c]), head, rows });
      continue;
    }

    if (LIST.test(line)) {
      const [list, next] = parseList(lines, i);
      blocks.push({ t: "list", list });
      i = next;
      continue;
    }

    const para: string[] = [line.trim()];
    i++;
    while (i < lines.length && !isBlank(lines[i]) && !startsBlock(lines, i)) {
      para.push(lines[i].trim());
      i++;
    }
    blocks.push({ t: "p", text: para.join("\n") });
  }
  return blocks;
}

// ---------------------------------------------------------------------------
// Inline rendering
// ---------------------------------------------------------------------------

const INLINE_SOURCE = [
  /(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/.source, //                                   1,2  code span
  /!\[([^\]\n]*)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"\n]*")?\s*\)/.source, //              3,4  image
  /\[((?:[^[\]\n]|\[[^\]\n]*\])+)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"\n]*")?\s*\)/.source, // 5,6 link
  /<((?:https?:\/\/|mailto:)[^>\s]+)>/.source, //                                     7    autolink
  /(?<![\w/@])(https?:\/\/[^\s<>]+)/.source, //                                        8    bare URL
  /\*\*(?=\S)([\s\S]*?\S)\*\*/.source, //                                             9    **bold**
  /(?<!\w)__(?=\S)([\s\S]*?\S)__(?!\w)/.source, //                                     10   __bold__
  /~~(?=\S)([\s\S]*?\S)~~/.source, //                                                  11   ~~strike~~
  /(?<![*\w])\*(?=[^\s*])([\s\S]*?[^\s*])\*(?![*\w])/.source, //                        12   *italic*
  /(?<!\w)_(?=[^\s_])([\s\S]*?[^\s_])_(?!\w)/.source, //                                13   _italic_
  /\\([\\`*_{}[\]()#+\-.!~|>])/.source, //                                             14   escape
  /(\n)/.source, //                                                                    15   line break
].join("|");

/** Trims sentence punctuation and unbalanced closers off a bare URL. */
function trimUrl(url: string): string {
  let u = url;
  for (;;) {
    const last = u.charAt(u.length - 1);
    if (/[.,:;!?"'*_~]/.test(last)) {
      u = u.slice(0, -1);
    } else if (last === ")" && (u.match(/\(/g)?.length ?? 0) < (u.match(/\)/g)?.length ?? 0)) {
      u = u.slice(0, -1);
    } else if (last === "]" && (u.match(/\[/g)?.length ?? 0) < (u.match(/\]/g)?.length ?? 0)) {
      u = u.slice(0, -1);
    } else {
      return u;
    }
  }
}

function RemoteImage({ href, alt }: { href: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <ExternalLink href={href}>
        <Icon name="image" className="nyx-md__link-icon" />
        {alt || "Image"}
      </ExternalLink>
    );
  }
  return (
    <a className="nyx-md__imglink" href={href} target="_blank" rel="noopener noreferrer" title="Open the original picture">
      <img className="nyx-md__img" src={`/api/image-proxy?url=${encodeURIComponent(href)}`} alt={alt || "Picture"} loading="lazy"
        onError={() => setFailed(true)} />
    </a>
  );
}

function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a className="nyx-md__link" href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

function renderInline(text: string, keyPrefix: string, depth = 0): ReactNode[] {
  if (!text) return [];
  if (depth > 4) return [text];
  const re = new RegExp(INLINE_SOURCE, "g");
  const out: ReactNode[] = [];
  let last = 0;
  let n = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const key = `${keyPrefix}.${n++}`;
    let end = re.lastIndex;
    let node: ReactNode;
    if (m[1] !== undefined) {
      let code = m[2];
      if (code.length > 2 && code.startsWith(" ") && code.endsWith(" ") && code.trim()) code = code.slice(1, -1);
      node = <code key={key} className="nyx-md__code">{code}</code>;
    } else if (m[4] !== undefined) {
      const local = safeImageSrc(m[4]);
      const remote = safeHref(m[4]);
      if (local && !remote) {
        node = <img key={key} className="nyx-md__img" src={local} alt={m[3]} loading="lazy" />;
      } else if (remote && /^https:/i.test(remote)) {
        // Request H15: show the picture. The engine fetches it, so the browser never contacts the site.
        node = <RemoteImage key={key} href={remote} alt={m[3]} />;
      } else if (remote) {
        node = (
          <ExternalLink key={key} href={remote}>
            <Icon name="image" className="nyx-md__link-icon" />
            {m[3] || "Image"}
          </ExternalLink>
        );
      } else {
        node = m[3];
      }
    } else if (m[6] !== undefined) {
      const href = safeHref(m[6]);
      const label = renderInline(m[5], key, depth + 1);
      node = href ? <ExternalLink key={key} href={href}>{label}</ExternalLink> : <Fragment key={key}>{label}</Fragment>;
    } else if (m[7] !== undefined) {
      const href = safeHref(m[7]);
      node = href ? <ExternalLink key={key} href={href}>{m[7].replace(/^mailto:/i, "")}</ExternalLink> : m[7];
    } else if (m[8] !== undefined) {
      const url = trimUrl(m[8]);
      end = m.index + url.length;
      re.lastIndex = end;
      const href = safeHref(url);
      node = href ? <ExternalLink key={key} href={href}>{url}</ExternalLink> : url;
    } else if (m[9] !== undefined || m[10] !== undefined) {
      node = <strong key={key}>{renderInline(m[9] ?? m[10], key, depth + 1)}</strong>;
    } else if (m[11] !== undefined) {
      node = <del key={key}>{renderInline(m[11], key, depth + 1)}</del>;
    } else if (m[12] !== undefined || m[13] !== undefined) {
      node = <em key={key}>{renderInline(m[12] ?? m[13], key, depth + 1)}</em>;
    } else if (m[14] !== undefined) {
      node = m[14];
    } else {
      node = <br key={key} />;
    }
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(node);
    last = end;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ---------------------------------------------------------------------------
// Block rendering
// ---------------------------------------------------------------------------

function Caret() {
  return <span className="nyx-md__caret" aria-hidden="true" />;
}

function CodeBlock({ lang, code, open, caret }: { lang: string; code: string; open: boolean; caret: boolean }) {
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const label = lang || "text";
  const onCopy = async () => {
    const ok = await copyToClipboard(code);
    setCopy(ok ? "copied" : "failed");
    window.setTimeout(() => setCopy("idle"), 1800);
  };
  return (
    <figure className="nyx-md__codeblock" data-open={open || undefined} data-lang={label}>
      <figcaption className="nyx-md__codebar">
        <span className="nyx-md__lang">{label}</span>
        {open && <span className="nyx-md__code-live">Writing…</span>}
        <button type="button" className="nyx-btn nyx-btn--ghost nyx-btn--sm nyx-md__copy" onClick={onCopy} aria-label={`Copy ${label} code`}>
          <Icon name={copy === "copied" ? "check" : copy === "failed" ? "alert" : "copy"} />
          <span aria-live="polite">{copy === "copied" ? "Copied" : copy === "failed" ? "Couldn’t copy" : "Copy"}</span>
        </button>
      </figcaption>
      <pre className="nyx-md__pre" tabIndex={0} aria-label={`${label} code`}>
        <code>
          {code}
          {caret && <Caret />}
        </code>
      </pre>
    </figure>
  );
}

function ListView({ list, keyPrefix, caret }: { list: ListModel; keyPrefix: string; caret: boolean }) {
  const Tag = list.ordered ? "ol" : "ul";
  return (
    <Tag className="nyx-md__list" data-ordered={list.ordered || undefined} start={list.ordered && list.start !== 1 ? list.start : undefined}>
      {list.items.map((item, idx) => {
        const key = `${keyPrefix}.${idx}`;
        const isLast = idx === list.items.length - 1;
        return (
          <li key={key} className="nyx-md__li" data-task={item.checked !== undefined || undefined}>
            {item.checked !== undefined && (
              <span className="nyx-md__task" data-checked={item.checked} role="img" aria-label={item.checked ? "Done:" : "To do:"}>
                {item.checked && <Icon name="check" />}
              </span>
            )}
            {renderInline(item.text, key)}
            {caret && isLast && !item.children && <Caret />}
            {item.children && <ListView list={item.children} keyPrefix={`${key}c`} caret={caret && isLast} />}
          </li>
        );
      })}
    </Tag>
  );
}

function BlockView({ block, k, caret }: { block: Block; k: string; caret: boolean }) {
  switch (block.t) {
    case "p":
      return (
        <p className="nyx-md__p">
          {renderInline(block.text, k)}
          {caret && <Caret />}
        </p>
      );
    case "h": {
      // Offset by two so a reply's "# Title" never outranks the page's own headings.
      const Tag = `h${Math.min(6, block.level + 2)}` as "h3";
      return (
        <Tag className="nyx-md__h" data-level={block.level}>
          {renderInline(block.text, k)}
          {caret && <Caret />}
        </Tag>
      );
    }
    case "code":
      if (!block.open && ["chart", "graph", "plot"].includes(block.lang.toLowerCase())) return <ChartBox source={block.code} />;
      // A question to click through, and the plan to approve (Project Null N84, N85).
      if (!block.open && ["question", "ask"].includes(block.lang.toLowerCase())) return <QuestionCard source={block.code} />;
      if (!block.open && block.lang.toLowerCase() === "plan") return <PlanCard source={block.code} />;
      if (["python", "py", "python3"].includes(block.lang.toLowerCase())) return <PythonBox code={block.code} open={block.open} />;
      return <CodeBlock lang={block.lang} code={block.code} open={block.open} caret={caret} />;
    case "hr":
      return (
        <>
          <hr className="nyx-md__hr" />
          {caret && <Caret />}
        </>
      );
    case "quote":
      return (
        <blockquote className="nyx-md__quote">
          {block.blocks.map((b, i) => (
            <BlockView key={`${k}.${i}`} block={b} k={`${k}.${i}`} caret={caret && i === block.blocks.length - 1} />
          ))}
        </blockquote>
      );
    case "list":
      return <ListView list={block.list} keyPrefix={k} caret={caret} />;
    case "table":
      return (
        <div className="nyx-md__table-wrap" role="region" aria-label="Table" tabIndex={0}>
          <table className="nyx-md__table">
            <thead>
              <tr>
                {block.head.map((cell, c) => (
                  <th key={c} scope="col" data-align={block.align[c]}>
                    {renderInline(cell, `${k}.h${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} data-align={block.align[c]}>
                      {renderInline(cell, `${k}.${r}.${c}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {caret && <Caret />}
        </div>
      );
  }
}

/** Question and plan blocks the model wrote as XML-ish tags, turned into fences.
 *
 * The prompt asks for ```question, and most models oblige — but some write
 * <question>…</question> instead, and the owner then sees raw JSON in the chat.
 * Both forms mean the same thing, so both get rendered as a card.
 */
function normalizeCardBlocks(text: string): string {
  const tagged = text.replace(/<(question|questions|plan)>\s*([\s\S]*?)\s*<\/\1>/gi, (_all, tag: string, body: string) =>
    `\n\`\`\`${tag.toLowerCase() === "plan" ? "plan" : "question"}\n${body.trim()}\n\`\`\`\n`);
  // …and the JSON that arrived with no fence at all (small models drop it).
  const spans = [
    ...findCardJson(tagged, "question").map((span) => ({ ...span, lang: "question" })),
    ...findCardJson(tagged, "plan").map((span) => ({ ...span, lang: "plan" })),
  ].sort((a, b) => a.start - b.start);
  if (spans.length === 0) return tagged;

  let out = "";
  let at = 0;
  for (const span of spans) {
    if (span.start < at) continue;  // overlapping matches: the first one wins
    const before = tagged.slice(at, span.start);
    // An odd number of fences before this point means we are inside a code block already.
    if ((tagged.slice(0, span.start).match(/```/g) ?? []).length % 2 === 1) continue;
    out += before + `\n\`\`\`${span.lang}\n${tagged.slice(span.start, span.end)}\n\`\`\`\n`;
    at = span.end;
  }
  return out + tagged.slice(at);
}

export function Markdown({ text, streaming }: MarkdownProps) {
  const blocks = useMemo(() => parseBlocks(normalizeCardBlocks((text ?? "").replace(/\r\n?/g, "\n"))), [text]);
  if (blocks.length === 0) {
    return streaming ? (
      <div className="nyx-md" data-streaming="true">
        <Caret />
      </div>
    ) : null;
  }
  return (
    <div className="nyx-md" data-streaming={streaming || undefined}>
      {blocks.map((block, i) => (
        <BlockView key={i} block={block} k={`b${i}`} caret={!!streaming && i === blocks.length - 1} />
      ))}
    </div>
  );
}
