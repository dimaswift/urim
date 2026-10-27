import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Two apps, one API (`urim review`, port 8765): the War Room (index.html) for reviewing, and the
// Illuminated Codex (codex.html) for reading. The dev server proxies /api to the Python server.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      input: { warroom: resolve(__dirname, "index.html"), codex: resolve(__dirname, "codex.html") },
    },
  },
});
