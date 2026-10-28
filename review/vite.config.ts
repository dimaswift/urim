import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Two apps, one API (`urim review`, port 8765): the War Room (index.html) for reviewing, and the
// Illuminated Codex (codex.html) for reading. The dev server proxies /api to the Python server.
// `--mode site` (.env.site) builds the static copy for GitHub Pages, which reads files instead.
export default defineConfig({
  plugins: [react()],
  // Relative asset URLs: served at / by `urim review`, under /<repo>/ on GitHub Pages.
  base: "./",
  // The English messages live with the Python package (urim/i18n/en), one level up.
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" }, fs: { allow: [".."] } },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      input: { warroom: resolve(__dirname, "index.html"), codex: resolve(__dirname, "codex.html") },
    },
  },
});
