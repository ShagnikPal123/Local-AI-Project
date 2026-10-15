import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import "./nyx.css";
import "./shell.css";
import "./style/styles.css";
import "./style/studio.css";
import "./style/desk.css";
import "./style/palettes.css";
import "./style/transitions.css";
import "./style/desk-everywhere.css";
import { bootMix } from "./style/styleMix";
import { bootAppearance } from "./style/appearance";
import { startMotion } from "./style/motion";

bootMix();
bootAppearance();
startMotion();
import { registerShellCache } from "./engine";
import { setToken } from "./api";

// A rebuild — an update, Apply or Improve — replaces the hashed chunks while this page is open. The next tab
// that loads lazily then fails to import, React unmounts the whole app, and the window goes blank. Load the
// new build instead; once only, so a chunk that is truly broken still shows its error rather than looping.
const RELOADED_AT = "nyx.chunkReloadAt";
let reloading = false;
window.addEventListener("vite:preloadError", (event) => {
  if (reloading) return;
  try {
    if (Date.now() - Number(sessionStorage.getItem(RELOADED_AT) || 0) < 30_000) return;
  } catch {
    return; // no storage to remember the attempt by: never risk a reload loop
  }
  reloading = true;
  event.preventDefault();
  void reloadWhenServed();
});

/** A build empties its folder before writing the new one; reloading into that moment showed a bare
 * "Internal Server Error" page. Wait (up to ~30 s) until the page is served again. */
async function reloadWhenServed(): Promise<void> {
  for (let attempt = 0; attempt < 30; attempt++) {
    try {
      if ((await fetch("/", { cache: "no-store" })).ok) break;
    } catch {
      /* engine restarting — keep waiting */
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  try {
    sessionStorage.setItem(RELOADED_AT, String(Date.now()));
  } catch {
    return;
  }
  window.location.reload();
}

/** Inside Nyx's own desktop window (app_window.py, marked by ?shell=app) the window hands over the owner's session
 * through pywebview's bridge, so the app opens signed in like a desktop app. A browser tab never waits for it. */
async function appWindowSession(): Promise<void> {
  if (new URLSearchParams(window.location.search).get("shell") !== "app") return;
  type Bridge = { token?: () => Promise<string> };
  const bridge = () => (window as unknown as { pywebview?: { api?: Bridge } }).pywebview?.api;
  const started = Date.now();
  while (!bridge()?.token && Date.now() - started < 3000) await new Promise((resolve) => setTimeout(resolve, 50));
  const token = bridge()?.token ? await bridge()!.token!() : "";
  if (token) setToken(token);
}

void appWindowSession().finally(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode><App /></StrictMode>
  );
});

// Lets the page load, and offer "Turn on Nyx", even while the engine is off.
registerShellCache();
