/** Keeps the page in step with the desktop's colours while "Sync with desktop" is on (Settings › Appearance).
 *
 * The engine reads the Windows accent and the wallpaper colour (desktop_theme.py); this hook asks for them when syncing
 * is switched on, when the window gets focus again (the owner may have just changed their wallpaper), and every five
 * minutes. Off, it hands the colours back to the owner's own pick.
 */

import { useEffect } from "react";
import { api } from "../api";
import { readAppearance, setDesktopTheme, type DesktopTheme } from "./appearance";

export async function fetchDesktopTheme(): Promise<DesktopTheme | null> {
  const result = await api.get<DesktopTheme>("/api/desktop-theme");
  return result.ok ? result.data : null;
}

export function useDesktopSync(): void {
  useEffect(() => {
    let timer = 0;
    let alive = true;
    const refresh = async () => {
      if (!readAppearance().sync) { setDesktopTheme(null); return; }
      const theme = await fetchDesktopTheme();
      if (alive && readAppearance().sync) setDesktopTheme(theme && theme.available ? theme : null);
    };
    const onFocus = () => void refresh();
    window.addEventListener("ichos:appearance", onFocus);
    window.addEventListener("focus", onFocus);
    timer = window.setInterval(() => void refresh(), 5 * 60_000);
    void refresh();
    return () => {
      alive = false;
      window.clearInterval(timer);
      window.removeEventListener("ichos:appearance", onFocus);
      window.removeEventListener("focus", onFocus);
    };
  }, []);
}
