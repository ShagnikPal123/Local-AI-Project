/** Presentational hooks for the chat components (no data fetching). */

import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

/** A clock that ticks only while `active`, so idle history costs nothing. */
export function useNow(active: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [active, intervalMs]);
  return now;
}

/** A disclosure whose default follows the data until the person touches it.
 *
 * `defaultOpen` can change over time (open while streaming, closed when done);
 * once the person toggles, their choice wins for the life of the component.
 */
export function useAutoDisclosure(defaultOpen: boolean): [boolean, () => void, (open: boolean) => void] {
  const [override, setOverride] = useState<boolean | null>(null);
  const open = override ?? defaultOpen;
  const toggle = useCallback(() => setOverride((o) => !(o ?? defaultOpen)), [defaultOpen]);
  const set = useCallback((value: boolean) => setOverride(value), []);
  return [open, toggle, set];
}

/** A boolean that flips back to false after `ms` (for "Copied" style feedback). */
export function useTransientFlag(ms = 1600): [boolean, () => void] {
  const [on, setOn] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const trigger = useCallback(() => {
    setOn(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOn(false), ms);
  }, [ms]);
  return [on, trigger];
}

/** Rate-limits a changing string for screen-reader announcements.
 *
 * Status text can change several times a second while tools run; announcing
 * each change would talk over the person. The latest value is emitted at most
 * once per `ms`, and the final value always lands.
 */
export function useThrottledText(text: string, ms = 4000): string {
  const [out, setOut] = useState(text);
  const last = useRef(0);
  const pending = useRef<number | undefined>(undefined);
  useEffect(() => {
    const now = Date.now();
    const wait = last.current + ms - now;
    window.clearTimeout(pending.current);
    if (wait <= 0) {
      last.current = now;
      setOut(text);
    } else {
      pending.current = window.setTimeout(() => {
        last.current = Date.now();
        setOut(text);
      }, wait);
    }
    return () => window.clearTimeout(pending.current);
  }, [text, ms]);
  return out;
}

/** Clipboard write with a fallback for non-secure origins (LAN http), where
 * `navigator.clipboard` is undefined. Resolves to whether it worked. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

/** Calls `onOutside` for pointer-downs outside `ref` while `active`. */
export function useDismiss(ref: RefObject<HTMLElement | null>, active: boolean, onOutside: () => void): void {
  const cb = useRef(onOutside);
  useEffect(() => {
    cb.current = onOutside;
  });
  useEffect(() => {
    if (!active) return;
    const onDown = (e: PointerEvent) => {
      const el = ref.current;
      if (el && e.target instanceof Node && !el.contains(e.target)) cb.current();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [ref, active]);
}
