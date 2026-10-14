/** The hands-off sidebar's desktop window (sidebar_window.py loads /sidebar), signed in the same way as the notch. */

import { createRoot } from "react-dom/client";
import { getToken, setToken } from "../api";
import { hostToken } from "../notch/hostToken";
import { Sidebar } from "./Sidebar";

void hostToken().then((token) => {
  if (token) setToken(token);
  else if (!getToken()) console.warn("Sidebar: no session — open it from Ichos (Equalize → Notch controls).");
  createRoot(document.getElementById("root")!).render(<Sidebar />);
});
