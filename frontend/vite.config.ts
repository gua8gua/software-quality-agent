import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";
import prefixSelector from "postcss-prefix-selector";

export default defineConfig({
  base: "./",
  css: { postcss: { plugins: [prefixSelector({
    prefix: ".pdf-frame",
    includeFiles: [/pdfjs-dist[\\/]web[\\/]pdf_viewer\.css$/],
    transform(prefix, selector, prefixedSelector, _file, rule) {
      // Native nested rules already inherit the outer namespace. Prefixing
      // their relative selectors again would require a second PDF container.
      for (let parent = rule.parent; parent; parent = parent.parent) {
        if (parent.type === "rule") return selector;
      }
      if (/^(html|body|:root)(?=[\s:.#\[]|$)/.test(selector)) {
        return selector.replace(/^(html\s+body|html|body|:root)/, prefix);
      }
      return prefixedSelector;
    },
  })] } },
  plugins: [react(), viteStaticCopy({ targets: ["cmaps", "standard_fonts", "wasm", "web/images"].map(folder => ({
    src: `node_modules/pdfjs-dist/${folder}/*`, dest: `pdfjs/${folder === "web/images" ? "images" : folder}`, rename: { stripBase: true },
  })) })],
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/api/agent": { target: process.env.QUALITY_AGENT_URL || "http://127.0.0.1:8001", changeOrigin: true },
      "/api/v1": { target: process.env.QUALITY_BACKEND_URL || "http://127.0.0.1:8000", changeOrigin: true },
      "/api": { target: process.env.QUALITY_AGENT_URL || "http://127.0.0.1:8001", changeOrigin: true },
    },
  },
});
