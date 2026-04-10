const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
      continue;
    }
    args[key] = next;
    i += 1;
  }
  return args;
}

function resolveBrowser(preferred) {
  const candidates = preferred ? [preferred] : [
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
  ];
  for (const candidate of candidates) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  throw new Error('No supported browser executable found.');
}

function sanitizeProfile(name) {
  return String(name || 'default').replace(/[^a-zA-Z0-9._-]/g, '_');
}

(async () => {
  const args = parseArgs(process.argv);
  const executablePath = resolveBrowser(args.browser);
  const profile = sanitizeProfile(args.profile || 'default');
  const userDataDir = path.join('D:\\codex\\tools\\browser-automation', 'profiles', profile);
  const url = args.url || 'about:blank';
  fs.mkdirSync(userDataDir, { recursive: true });

  const context = await chromium.launchPersistentContext(userDataDir, {
    executablePath,
    headless: false,
    viewport: { width: 1440, height: 960 },
  });

  const page = context.pages()[0] || await context.newPage();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: Number(args.timeout || 30000) }).catch(() => {});

  process.stdout.write(JSON.stringify({
    ok: true,
    message: 'Login session opened. Sign in manually, then close the browser window to persist the session.',
    browser: executablePath,
    profile,
    profileDir: userDataDir,
    url,
    timestamp: new Date().toISOString()
  }, null, 2) + '\n');

  await new Promise(resolve => context.on('close', resolve));
})().catch(error => {
  process.stderr.write(String((error && error.stack) || error));
  process.exit(1);
});
