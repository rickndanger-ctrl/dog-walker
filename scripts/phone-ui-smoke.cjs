#!/usr/bin/env node
// Real browser rendering against inert local phone fixtures; no live pairing or walk.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.DOG_WALKER_PLAYWRIGHT_MODULE || path.join(process.env.HOME,'Projects/hermes-army/node_modules/playwright'));
const root = path.resolve(__dirname,'../phone');
const output = path.resolve(__dirname,'../artifacts/phone-ui');
fs.mkdirSync(output,{recursive:true});
const allowed = new Set(['index.html','style.css','app.js','sw.js','icon-192.png','icon-512.png','manifest.webmanifest']);
let actions = 0;
const server = http.createServer((req,res)=>{
  const filename = req.url === '/' ? 'index.html' : req.url.slice(1);
  if (req.url.startsWith('/api/')) {
    if(req.method !== 'GET') actions++;
    res.writeHead(401,{'Content-Type':'application/json'});res.end('{}');return;
  }
  if(!allowed.has(filename)){res.writeHead(404);res.end();return;}
  const types = {'.html':'text/html','.css':'text/css','.js':'application/javascript','.png':'image/png','.webmanifest':'application/manifest+json'};
  res.writeHead(200,{'Content-Type':types[path.extname(filename)]});res.end(fs.readFileSync(path.join(root,filename)));
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',chromiumSandbox:true});
  try {
    const context = await browser.newContext({viewport:{width:390,height:844},colorScheme:'dark',serviceWorkers:'block'});
    await context.route('**/*',r=>new URL(r.request().url()).origin===origin?r.continue():r.abort());
    const page = await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(origin);await page.locator('#pair').waitFor({state:'visible'});
    if(await page.locator('html').getAttribute('data-theme')!=='dark')throw Error('Initial dark theme missing');
    await page.screenshot({path:path.join(output,'dark.png'),fullPage:true});
    await page.locator('#theme-toggle').click();
    if(await page.locator('html').getAttribute('data-theme')!=='light')throw Error('Light toggle failed');
    const metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,background:getComputedStyle(document.documentElement).backgroundColor,buttonBackground:getComputedStyle(document.querySelector('#pair-form button')).backgroundColor,buttonText:getComputedStyle(document.querySelector('#pair-form button')).color}));
    if(metrics.overflow || metrics.background!=='rgb(255, 255, 255)' || metrics.buttonBackground===metrics.buttonText)throw Error(JSON.stringify(metrics));
    await page.screenshot({path:path.join(output,'light.png'),fullPage:true});
    await page.reload();if(await page.locator('html').getAttribute('data-theme')!=='light')throw Error('Theme did not persist');
    if(errors.length||actions)throw Error(JSON.stringify({errors,actions}));
    console.log('PASS: real Chromium phone themes, contrast, persistence and 390px layout; zero walk/pair actions.');
  } finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
