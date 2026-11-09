import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export default defineConfig({
  testDir: "./tests",
  timeout: 45000,
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
  },
  webServer: [
    {
      command: `"${path.join(root, ".venv/Scripts/python.exe")}" -m uvicorn backend.main:app --host 127.0.0.1 --port 18401`,
      cwd: root,
      url: "http://127.0.0.1:18401/api/v1/health",
      timeout: 30000,
      reuseExistingServer: false,
      env: {
        DATA_DIR: path.join(root, ".runtime/e2e-data"),
        OPENAI_API_KEY: "",
        DATABASE_URL: "",
        MYSQL_HOST: "",
        MYSQL_LOCAL_MANAGED: "false",
        AUTH_USERNAME: "browser-test",
        AUTH_PASSWORD: "browser-test-password",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      timeout: 30000,
      env: { API_PROXY: "http://127.0.0.1:18401" },
      reuseExistingServer: false,
    },
  ],
});
