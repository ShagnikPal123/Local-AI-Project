/** Whether this user has asked the OS for reduced motion.
 *
 * Lives on its own because more than one panel needs it and the value can change
 * mid-session (Windows lets you toggle animation effects without a reload), so a
 * one-shot `matchMedia(...).matches` at module load would go stale.
 */

import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    try {
      return window.matchMedia(QUERY).matches;
    } catch {
      return false;
    }
  });

  useEffect(() => {
    let media: MediaQueryList;
    try {
      media = window.matchMedia(QUERY);
    } catch {
      return;
    }
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
