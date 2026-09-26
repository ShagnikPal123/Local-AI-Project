import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import "./nyx.css";
import { registerShellCache } from "./engine";

createRoot(document.getElementById("root")!).render(
  <StrictMode><App /></StrictMode>
);

// Lets the page load, and offer "Turn on Nyx", even while the engine is off.
registerShellCache();
