import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build goes into the Python package, where the backend serves it. In development, `npm run dev`
// serves the pages and passes /api to a backend started with `uv run hobbes serve --port 8781`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/hobbes/web/static",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8781" },
  },
});
