import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
export default defineConfig({
  testDir: './e2e', testMatch: '*.playwright.mjs', workers: 1, timeout: 120000,
  use: { baseURL: 'http://127.0.0.1:15173', viewport: { width: 1440, height: 1000 },
    launchOptions: { executablePath: process.env.READER_CHROME || (existsSync(chrome) ? chrome : undefined) },
    trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  webServer: [
    { command: '../backend/.venv/bin/python ../backend/tests/reader_smoke_server.py',
      env: { PYTHONPATH: '../backend', READER_SMOKE_PORT: '18080', DATABASE_URL: 'sqlite://', APP_CONFIG_PATH: '../backend/config/config.example.yaml' }, url: 'http://127.0.0.1:18080/health', reuseExistingServer: false },
    { command: `npm run ${process.env.READER_TEST_PRODUCTION === '1' ? 'preview' : 'dev'} -- --host 127.0.0.1 --port 15173 --strictPort`,
      env: { VITE_PROXY_TARGET: 'http://127.0.0.1:18080' }, url: 'http://127.0.0.1:15173', reuseExistingServer: false },
  ],
});
