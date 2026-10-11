// One fresh browser per call. No persisted profile, form actions or downloads.
const fs = require('node:fs');
const path = require('node:path');
const LOCAL_ORIGIN = 'http://dogwalker.invalid';

function authorizeResource(input, address, method = 'GET') {
  const url = new URL(address);
  if (!['GET', 'HEAD'].includes(method) || url.username || url.password) return null;
  if (input.path && url.origin === LOCAL_ORIGIN) {
    try {
      const relative = decodeURIComponent(url.pathname).replace(/^\/+/, '');
      const parts = relative.split('/');
      if (parts.some(p => ['..', '.git', '.ssh', '.codex'].includes(p) || p.startsWith('.env'))) return null;
      const root = fs.realpathSync(input.root);
      const target = fs.realpathSync(path.join(root, relative));
      if (!target.startsWith(root + path.sep) || !fs.statSync(target).isFile() || fs.statSync(target).size > 2 * 1024 * 1024) return null;
      return {file: target};
    } catch { return null; }
  }
  if (['http:', 'https:'].includes(url.protocol) && input.origins.includes(url.origin)) return {network: true};
  return null;
}

async function inspect(input) {
  const {chromium} = require(input.playwright_module);
  const browser = await chromium.launch({headless: true, chromiumSandbox: true});
  try {
    const context = await browser.newContext({
      viewport: {width: input.width, height: input.height},
      acceptDownloads: false, serviceWorkers: 'block',
    });
    const errors = [];
    const blocked = new Set();
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      const permit = authorizeResource(input, url.href, route.request().method());
      if (permit?.file) {
        const types = {'.html': 'text/html', '.htm': 'text/html', '.css': 'text/css', '.js': 'text/javascript',
          '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
          '.jpeg': 'image/jpeg', '.txt': 'text/plain', '.md': 'text/plain'};
        await route.fulfill({status: 200, contentType: types[path.extname(permit.file)] || 'application/octet-stream', body: fs.readFileSync(permit.file)});
      }
      else if (permit?.network) await route.continue();
      else { blocked.add(url.origin); await route.abort('blockedbyclient'); }
    });
    // WebSockets cannot inherit broader network access than the HTTP route.
    await context.routeWebSocket('**/*', socket => socket.close());
    const page = await context.newPage();
    page.on('pageerror', err => { if (errors.length < 20) errors.push(String(err).slice(0, 300)); });
    page.on('dialog', dialog => dialog.dismiss());
    // Serve workspace files through an intercepted virtual origin instead of
    // file://, whose local-file loads need not pass through network routing.
    const url = input.path ? LOCAL_ORIGIN + '/' + path.relative(input.root, input.path).split(path.sep).map(encodeURIComponent).join('/') : input.url;
    await page.goto(url, {waitUntil: 'domcontentloaded', timeout: 20000});
    await page.waitForTimeout(250);
    const result = await page.evaluate(() => ({
      title: document.title,
      text: (document.body?.innerText || '').slice(0, 12000),
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      viewport: {width: innerWidth, height: innerHeight},
    }));
    return {...result, url: page.url(), errors: errors.slice(0, 20), blockedOrigins: [...blocked].slice(0, 20)};
  } finally { await browser.close(); }
}

if (require.main === module) {
  inspect(JSON.parse(fs.readFileSync(0, 'utf8')))
    .then(result => process.stdout.write(JSON.stringify(result)))
    .catch(err => { process.stderr.write(String(err)); process.exitCode = 1; });
}
module.exports = {inspect, authorizeResource};
