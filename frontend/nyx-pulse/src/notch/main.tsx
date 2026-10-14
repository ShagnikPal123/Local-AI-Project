/** The desktop notch window (notch_window.py loads /notch). It has no login screen: the host hands it the owner's
 * session through pywebview's bridge, so the token never travels in a URL. */

import { createRoot } from "react-dom/client";
import { getToken, setToken } from "../api";
import { hostToken } from "./hostToken";
import { Notch } from "./Notch";

void hostToken().then((token) => {
  if (token) setToken(token);
  else if (!getToken()) console.warn("Notch: no session — open it from Ichos (Equalize → Show on desktop).");
  createRoot(document.getElementById("root")!).render(<Notch />);
});
