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

function resolveProfileDir(profile) {
  const safe = sanitizeProfile(profile);
  const base = path.join('D:\\codex\\tools\\browser-automation', 'profiles');
  fs.mkdirSync(base, { recursive: true });
  return path.join(base, safe);
}

async function openContext(executablePath, args) {
  const headless = !args.headed;
  const viewport = { width: 1440, height: 960 };
  const proxyServer = args.proxy || process.env.ORCH_NETWORK_PROXY_URL || process.env.HTTPS_PROXY || process.env.HTTP_PROXY || '';
  const launchOptions = { executablePath, headless, viewport };
  if (proxyServer) {
    launchOptions.proxy = { server: proxyServer };
  }
  if (args.profile) {
    const userDataDir = resolveProfileDir(args.profile);
    const context = await chromium.launchPersistentContext(userDataDir, launchOptions);
    return { context, page: context.pages()[0] || await context.newPage(), profileDir: userDataDir, proxyServer };
  }
  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  return { context, page, browser, profileDir: null, proxyServer };
}

(async () => {
  const args = parseArgs(process.argv);
  const url = args.url;
  if (!url) throw new Error('Missing --url');
  const executablePath = resolveBrowser(args.browser);
  const timeout = Number(args.timeout || 20000);
  const waitUntil = args.waitUntil || 'domcontentloaded';
  const outFile = args.out || '';
  const screenshotFile = args.screenshot || '';
  const selector = args.selector || 'body';

  const { context, page, browser, profileDir, proxyServer } = await openContext(executablePath, args);
  try {
    await page.goto(url, { waitUntil, timeout });
    if (args.waitFor) {
      await page.waitForSelector(args.waitFor, { timeout });
    }
    const title = await page.title();
    const bodyText = await page.locator(selector).innerText().catch(() => '');
    const links = await page.locator('a').evaluateAll(nodes => nodes.slice(0, 20).map(node => ({
      text: (node.innerText || '').trim().slice(0, 120),
      href: node.href || ''
    })));
    const result = {
      ok: true,
      url: page.url(),
      title,
      browser: executablePath,
      profile: args.profile || null,
      profileDir,
      proxyServer: proxyServer || null,
      bodyText: bodyText.slice(0, 8000),
      links,
      timestamp: new Date().toISOString()
    };
    if (screenshotFile) {
      fs.mkdirSync(path.dirname(screenshotFile), { recursive: true });
      await page.screenshot({ path: screenshotFile, fullPage: true });
      result.screenshot = screenshotFile;
    }
    if (outFile) {
      fs.mkdirSync(path.dirname(outFile), { recursive: true });
      fs.writeFileSync(outFile, JSON.stringify(result, null, 2), 'utf8');
    }
    process.stdout.write(JSON.stringify(result, null, 2));
  } finally {
    await context.close();
    if (browser) {
      await browser.close();
    }
  }
})().catch(error => {
  process.stderr.write(String((error && error.stack) || error));
  process.exit(1);
});
