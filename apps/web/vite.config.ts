import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `13-web-client.md` §1: Vite, React 19, TypeScript strict.
// The dev server proxies the ops endpoints to the API so the browser makes
// same-origin requests and CORS is not in the way of a local look.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/healthz": "http://127.0.0.1:8000",
      "/readyz": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
    },
  },
});
