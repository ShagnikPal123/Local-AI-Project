/** The desktop notch window (notch_window.py loads /notch). It has no login screen: the host hands it the owner's
 * session through pywebview's bridge, so the token never travels in a URL. */

import { createRoot } from "react-dom/client";
import { getToken, setToken } from "../api";
import { Notch } from "./Notch";

type Bridge = { token?: () => Promise<string> };

async function hostToken(): Promise<string> {
  const read = async () => {
    const api = (window as unknown as { pywebview?: { api?: Bridge } }).pywebview?.api;
    return api?.token ? await api.token() : "";
  };
  // The bridge's functions arrive a moment after the page; a normal browser tab (testing) never gets them.
  return new Promise((resolve) => {
    const started = Date.now();
    const check = () => {
      const api = (window as unknown as { pywebview?: { api?: Bridge } }).pywebview?.api;
      if (api?.token) void read().then(resolve);
      else if (Date.now() - started > 4000) resolve("");
      else window.setTimeout(check, 50);
    };
    check();
  });
}

void hostToken().then((token) => {
  if (token) setToken(token);
  else if (!getToken()) console.warn("Notch: no session — open it from Ichos (Equalize → Show on desktop).");
  createRoot(document.getElementById("root")!).render(<Notch />);
});
