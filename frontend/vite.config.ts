import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies to the running Atlas API so the new shell talks to the
// real backend from the first commit. Nothing here is mocked.
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    // Not Vite's default 5173: Docker Desktop's WSL relay commonly holds that
    // port on Windows, which makes "is the dev server up?" checks ambiguous.
    port: 5273,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env["ATLAS_API_ORIGIN"] ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    // FastAPI serves this directory in built checkouts, including the
    // production Docker image. Backend-only editable installs retain the old
    // shell as an explicit fallback when no Node build exists.
    outDir: "dist",
    sourcemap: true,
  },
});
