/** The navigation bar's side for the look that is on, kept in <html data-nav> so the stylesheet can place it.
 *
 * The choice (Settings › Appearance) can be "the look decides", so the answer depends on whether Studio Glass is in the
 * mix; this hook follows both, and writes the result where `shell.css` reads it.
 */

import { useEffect, useState } from "react";
import { effectiveNav, readAppearance, type NavChoice, type NavSide } from "./appearance";

export function useNavSide(studio: boolean): NavSide {
  const [choice, setChoice] = useState<NavChoice>(() => readAppearance().nav);
  useEffect(() => {
    const onChange = (event: Event) => setChoice((event as CustomEvent<{ nav: NavChoice }>).detail.nav);
    window.addEventListener("ichos:appearance", onChange);
    return () => window.removeEventListener("ichos:appearance", onChange);
  }, []);
  const side = effectiveNav(choice, studio);
  useEffect(() => { document.documentElement.dataset.nav = side; }, [side]);
  return side;
}
