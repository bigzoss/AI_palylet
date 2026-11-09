import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // Set FRAMECRAFT_ALLOWED_HOSTS in frontend/.env.local for tunnel access.
  const { FRAMECRAFT_ALLOWED_HOSTS = "" } = loadEnv(
    mode,
    process.cwd(),
    "FRAMECRAFT_ALLOWED_HOSTS",
  );
  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      allowedHosts: FRAMECRAFT_ALLOWED_HOSTS.split(",")
        .map((host) => host.trim())
        .filter(Boolean),
      proxy: { "/api": process.env.API_PROXY || "http://127.0.0.1:18400" },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
