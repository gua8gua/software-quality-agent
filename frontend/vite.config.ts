import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { rollupOptions: { input: { main: "index.html", quality: "quality.html" } } },
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/api/v1": { target: process.env.QUALITY_BACKEND_URL || "http://127.0.0.1:8000", changeOrigin: true },
      "/api": { target: process.env.AGENT_BACKEND_URL || "http://127.0.0.1:8010", changeOrigin: true },
    },
  },
});
