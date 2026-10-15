import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built files are served by the trader itself (ichos_trader/server.py). `npm run dev` proxies
// the API to a trader running on the default port so the page can be worked on live.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8100" } },
});
