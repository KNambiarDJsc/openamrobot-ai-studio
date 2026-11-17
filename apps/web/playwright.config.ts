import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const ROOT = path.resolve(__dirname, "../..");
const PY = process.platform === "win32" ? path.join(ROOT, ".venv", "Scripts", "python.exe") : path.join(ROOT, ".venv", "bin", "python");
const API_PORT = 8010;
const WEB_PORT = 3010;
const DB = path.join(ROOT, "data", "e2e.db").replace(/\\/g, "/");

export default defineConfig({
  testDir: "./e2e",
  workers: 1, // one API process, one demo fixture state: tests run in order
  fullyParallel: false,
  timeout: 45_000,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, viewport: { width: 1440, height: 900 }, colorScheme: "dark" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    {
      command: `"${PY}" -m uvicorn studio_api.app:create_app --factory --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      cwd: ROOT,
      env: { STUDIO_MODE: "demo", DATABASE_URL: `sqlite:///${DB}`, CORS_ORIGINS: `http://127.0.0.1:${WEB_PORT},http://localhost:${WEB_PORT}`,
        POLL_INTERVAL_S: "0.2", EVAL_INTERVAL_S: "0.5" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx next build && npx next start -H 127.0.0.1 -p ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { NEXT_PUBLIC_API_URL: `http://127.0.0.1:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
