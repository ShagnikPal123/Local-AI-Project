import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Two entry points:
 *   index.html      -> the public landing page, with the two options
 *   app/index.html  -> the workspace itself, served at /app/
 *
 * Built as one project so a single deploy produces both.
 */
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(import.meta.dirname, "index.html"),
        app: resolve(import.meta.dirname, "app/index.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // NYX_API lets a session point a dev server at its own scratch engine instead of the owner's on 8000.
      "/api": process.env.NYX_API ?? "http://127.0.0.1:8000",
    },
  },
});
