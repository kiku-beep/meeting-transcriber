import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: 0,
  use: {
    baseURL: "http://localhost:1430",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: {
      args: ["--autoplay-policy=no-user-gesture-required"],
    },
  },
  webServer: {
    command: "npm run dev",
    port: 1430,
    timeout: 30_000,
    reuseExistingServer: true,
  },
  projects: [
    {
      name: "smoke",
      testMatch: /smoke\.spec\.ts/,
    },
    {
      name: "interaction",
      testMatch: /interaction\.spec\.ts/,
    },
    {
      name: "audio",
      testMatch: /audio\.spec\.ts/,
    },
    {
      name: "settings",
      testMatch: /settings\.spec\.ts/,
    },
  ],
});
