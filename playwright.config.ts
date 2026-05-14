import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/playwright',
  testMatch: '**/*.{spec,test}.ts',
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: `http://127.0.0.1:${process.env.PORT || 8199}`,
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
});
