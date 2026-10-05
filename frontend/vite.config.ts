import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the API runs on :8890 (python -m searxng_control.main) and Vite proxies to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: { "/api": { target: "http://127.0.0.1:8890", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
