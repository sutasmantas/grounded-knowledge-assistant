import { defineConfig, devices } from "@playwright/test";

/** The suite drives the real Atlas API, not a mock. Playwright starts both the
 *  backend and the dev server so a run is self-contained. `ATLAS_PYTHON` lets
 *  CI point at whichever interpreter has the project installed; the default is
 *  the worktree venv, resolved relative to the API server's own cwd. */
const python =
  process.env["ATLAS_PYTHON"] ??
  (process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python");

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 1 : 0,
  workers: 1,
  reporter: process.env["CI"] ? [["github"], ["list"]] : [["list"]],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: "http://127.0.0.1:5273",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop-1440",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "laptop-1024",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1024, height: 800 } },
    },
    {
      name: "mobile-390",
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
    },
  ],
  webServer: [
    {
      // Deterministic no-key mode: hash embeddings and the extractive
      // generator, so screenshots and assertions do not depend on a provider.
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: "..",
      url: "http://127.0.0.1:8000/api/health/ready",
      reuseExistingServer: !process.env["CI"],
      timeout: 180_000,
      env: {
        ATLAS_EMBEDDING_PROVIDER: "hash",
        ATLAS_GENERATION_PROVIDER: "extractive",
        ATLAS_DATA_DIR: "data/runtime-e2e",
      },
    },
    {
      command: "npx vite --host 127.0.0.1 --port 5273",
      url: "http://127.0.0.1:5273/",
      reuseExistingServer: !process.env["CI"],
      timeout: 120_000,
    },
  ],
});
