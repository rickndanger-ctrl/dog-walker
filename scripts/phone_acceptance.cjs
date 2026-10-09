/* Opt-in mobile browser test against the actual private HTTPS companion.
 * Requires Playwright. Pairing credentials are read locally, never logged.
 */
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const {chromium, devices} = require(process.env.DOG_WALKER_PLAYWRIGHT_MODULE || "playwright");
const root = path.resolve(__dirname, "..");
const home = require("node:os").homedir();
const config = JSON.parse(fs.readFileSync(path.join(home, ".config/dog-walker/phone.json")));
const key = JSON.parse(fs.readFileSync(path.join(home, ".local/share/dog-walker/phone-secret.json")));
(async () => {
  const browser = await chromium.launch({headless: true});
  const errors = [];
  try {
    for (const device of ["iPhone 13", "Pixel 7"]) {
      const context = await browser.newContext({...devices[device], serviceWorkers: "allow"});
      const page = await context.newPage();
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(config.origin, {waitUntil: "domcontentloaded"});
      await page.locator("#pair").waitFor({state: "visible"});
      await page.locator("#code").fill(key.pair_code);
      await page.locator("#pair-form button").click();
      await page.locator("#dashboard").waitFor({state: "visible"});
      assert.equal(await page.locator("#code").inputValue(), "");
      assert.equal(await page.evaluate(() => window.isSecureContext), true);
      const cookie = (await context.cookies()).find(c => c.name === "dogwalker");
      assert(cookie && cookie.secure && cookie.httpOnly && cookie.sameSite === "Strict");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.evaluate(async () => { const registration = await navigator.serviceWorker.ready; return registration.active.state; });
      const cached = await page.evaluate(async () => { const result = []; for (const name of await caches.keys()) for (const request of await (await caches.open(name)).keys()) result.push(new URL(request.url).pathname); return result; });
      assert(cached.length > 0 && cached.every(p => !p.startsWith("/api/")));
      if (device === "iPhone 13") await page.screenshot({path: path.join(root, "artifacts/phone-mobile.png"), fullPage: true});
      await context.setOffline(true);
      await page.reload({waitUntil: "domcontentloaded"});
      await page.waitForFunction(() => document.querySelector("#connection").textContent === "Disconnected");
      assert.equal(await page.locator("#approve").isEnabled(), false);
      assert.equal(await page.locator("#retry").isEnabled(), false);
      await context.setOffline(false);
      await page.reload({waitUntil: "domcontentloaded"});
      await page.locator("#dashboard").waitFor({state: "visible"});
      await context.close();
      console.log(`PASS: ${device} emulation, private HTTPS, pairing, secure cookie, installable shell, no overflow, offline actions disabled, reconnect.`);
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(root, "artifacts/phone-browser-acceptance.json"), JSON.stringify({devices: ["iPhone 13 (Chromium emulation)", "Pixel 7 (Chromium emulation)"], https_verified: true, pairing_verified: true, cookie_secure: true, offline_actions_disabled: true, api_not_cached: true, javascript_errors: errors, physical_phone_tested: false}, null, 2) + "\n");
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
