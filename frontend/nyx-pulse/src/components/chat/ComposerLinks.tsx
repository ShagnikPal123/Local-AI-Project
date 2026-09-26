/** Links in the box you are typing in: lit up, and openable.
 *
 * A textarea cannot hold a clickable anchor, so the text is drawn twice: this
 * mirror sits exactly behind the textarea with the same type, padding and
 * wrapping, and paints a highlight behind every link. The textarea itself stays
 * on top with a see-through background, so the owner types into the real thing
 * and only the colour comes from here.
 *
 * Clicking a link in a box you are editing is a trap — it would fire every time
 * the caret is placed. So hovering a link (or putting the caret in one) offers a
 * small "Open" chip, the way a document editor does, and Ctrl/Cmd+click opens it
 * straight away.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { findLinks, type LinkSpan } from "./linkify";

type Props = {
  value: string;
  textareaRef: { current: HTMLTextAreaElement | null };
  /** Where the caret is, so a link the caret sits in offers itself too. */
  caret?: number;
};

export function ComposerLinks({ value, textareaRef, caret }: Props) {
  const mirrorRef = useRef<HTMLDivElement>(null);
  const [spans, setSpans] = useState<LinkSpan[]>([]);
  const [chip, setChip] = useState<{ span: LinkSpan; left: number; top: number } | null>(null);

  useEffect(() => { setSpans(findLinks(value)); }, [value]);

  // The mirror scrolls with the textarea, or a long draft would drift apart.
  useLayoutEffect(() => {
    const area = textareaRef.current;
    const mirror = mirrorRef.current;
    if (!area || !mirror) return;
    const sync = () => { mirror.scrollTop = area.scrollTop; mirror.scrollLeft = area.scrollLeft; };
    sync();
    area.addEventListener("scroll", sync);
    return () => area.removeEventListener("scroll", sync);
  }, [textareaRef, value]);

  /** The link under a point on screen, using the highlight's own boxes. */
  const spanAt = useCallback((x: number, y: number): { span: LinkSpan; rect: DOMRect } | null => {
    const mirror = mirrorRef.current;
    if (!mirror) return null;
    const marks = Array.from(mirror.querySelectorAll<HTMLElement>("[data-link-index]"));
    for (const mark of marks) {
      for (const rect of Array.from(mark.getClientRects())) {
        if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
          const index = Number(mark.dataset.linkIndex);
          const span = spans[index];
          if (span) return { span, rect: rect as DOMRect };
        }
      }
    }
    return null;
  }, [spans]);

  const showChipFor = useCallback((found: { span: LinkSpan; rect: DOMRect } | null) => {
    if (!found) { setChip(null); return; }
    setChip({ span: found.span, left: found.rect.left, top: found.rect.top });
  }, []);

  useEffect(() => {
    const area = textareaRef.current;
    if (!area) return;
    let inside = false;

    const onMove = (event: MouseEvent) => {
      const found = spanAt(event.clientX, event.clientY);
      inside = Boolean(found);
      area.classList.toggle("is-over-link", inside && (event.ctrlKey || event.metaKey));
      showChipFor(found);
    };
    const onLeave = () => {
      inside = false;
      area.classList.remove("is-over-link");
      // Give the pointer a moment to reach the chip itself.
      window.setTimeout(() => setChip((current) => (current && !document.querySelector(".composer-link-chip:hover") ? null : current)), 260);
    };
    const onClick = (event: MouseEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const found = spanAt(event.clientX, event.clientY);
      if (!found) return;
      event.preventDefault();
      window.open(found.span.href, "_blank", "noopener,noreferrer");
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Control" || event.key === "Meta") area.classList.toggle("is-over-link", inside);
    };
    const onKeyUp = () => area.classList.remove("is-over-link");

    area.addEventListener("mousemove", onMove);
    area.addEventListener("mouseleave", onLeave);
    area.addEventListener("click", onClick);
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      area.removeEventListener("mousemove", onMove);
      area.removeEventListener("mouseleave", onLeave);
      area.removeEventListener("click", onClick);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [textareaRef, spanAt, showChipFor]);

  // The caret sitting inside a link offers it too, for keyboard-only use.
  useEffect(() => {
    if (caret === undefined || chip) return;
    const span = spans.find((s) => caret > s.start && caret <= s.end);
    if (!span) return;
    const mirror = mirrorRef.current;
    const mark = mirror?.querySelector<HTMLElement>(`[data-link-index="${spans.indexOf(span)}"]`);
    const rect = mark?.getClientRects()[0];
    if (rect) setChip({ span, left: rect.left, top: rect.top });
  }, [caret, spans, chip]);

  if (!spans.length) return <div className="composer-mirror" aria-hidden="true" ref={mirrorRef} />;

  const pieces: React.ReactNode[] = [];
  let at = 0;
  spans.forEach((span, index) => {
    if (span.start > at) pieces.push(value.slice(at, span.start));
    pieces.push(
      <mark key={index} className="composer-link" data-link-index={index}>{span.text}</mark>,
    );
    at = span.end;
  });
  pieces.push(value.slice(at));

  return (
    <>
      <div className="composer-mirror" aria-hidden="true" ref={mirrorRef}>{pieces}</div>
      {chip && createPortal(
        // Through a portal on purpose: the chat sheet is a glass surface, and an
        // ancestor with a backdrop filter makes `position: fixed` measure from
        // that surface instead of the window, which put the chip off screen.
        <button
          type="button"
          className="composer-link-chip"
          style={{ left: chip.left, top: chip.top }}
          onMouseLeave={() => setChip(null)}
          onClick={() => { window.open(chip.span.href, "_blank", "noopener,noreferrer"); setChip(null); }}
          title={chip.span.href}
        >
          Open<span aria-hidden="true"> ↗</span>
        </button>,
        document.body,
      )}
    </>
  );
}
