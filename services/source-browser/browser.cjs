// Headed Chrome and bounded serialization adapted from the upstreams in provenance.json.
const {createRequire} = require('node:module');
const readline = require('node:readline');
const MAX_PAGE = 2 * 1024 * 1024;
const MAX_IMAGE = 16 * 1024 * 1024;
let browser;
const next = new Map();

function allowed(raw, command, navigation = false) {
  try {
    const u = new URL(raw), target = new URL(command.url);
    if (u.protocol !== 'https:' || u.username || u.password || u.hash || u.port) return false;
    const path = decodeURIComponent(u.pathname);
    const article = title => !!title && !/[/%\x00-\x1f\x7f]/.test(title) &&
      (!title.includes(':') || !command.namespaces.includes(title.split(':')[0].replaceAll('_', ' ').trim().toLowerCase()));
    if (command.kind === 'goodreads') {
      if (['www.goodreads.com', 'goodreads.com'].includes(u.hostname))
        return (u.pathname === '/search' && [...u.searchParams.keys()].every(k => k === 'q')) ||
          (/^\/book\/show\/\d+[^/]*$/.test(u.pathname) && [...u.searchParams.keys()].every(k => ['from_search','from_srp','qid','rank'].includes(k)));
      return !navigation && command.images.includes(u.hostname) && /\.(jpg|jpeg|png)$/i.test(path);
    }
    if (command.kind === 'image') return u.hostname === target.hostname && u.pathname === target.pathname && !u.search;
    if (u.hostname !== target.hostname || !command.wikis.includes(u.hostname)) return false;
    if (command.kind === 'lexicanum_search') {
      return u.pathname === '/mediawiki/index.php' && [...u.searchParams.keys()].length === 5 &&
        ['title','search','fulltext','limit','ns0'].every(k => u.searchParams.getAll(k).length === 1) &&
        u.searchParams.get('title') === 'Special:Search' && u.searchParams.get('fulltext') === '1' &&
        u.searchParams.get('limit') === '5' && u.searchParams.get('ns0') === '1' &&
        !!u.searchParams.get('search') && u.searchParams.get('search').length <= 600 &&
        !/[\x00-\x1f\x7f]/.test(u.searchParams.get('search'));
    }
    if (path.startsWith('/wiki/') && !u.search && article(path.slice(6))) return true;
    return u.pathname === '/mediawiki/index.php' && [...u.searchParams.keys()].length === 2 &&
      (u.searchParams.get('title') || '').startsWith('Special:Export/') && article(u.searchParams.get('title').slice('Special:Export/'.length)) && u.searchParams.get('curonly') === '1';
  } catch { return false; }
}
function challenged(status, headers, text) {
  return status === 403 || headers['cf-mitigated'] === 'challenge' || /<title>\s*(Just a moment|Access Denied)|captcha|aws-waf-token|challenge-platform/i.test(text);
}
function original(src, base) {
  const match = src.match(/^(\/mediawiki\/images)\/thumb\/([a-f0-9]\/[a-f0-9]{2}\/[^/]+\.(?:jpg|jpeg|png))\/[^/]+$/i);
  return match && !/\/Book2\.jpg$/i.test(match[2]) ? new URL(match[1] + '/' + match[2], base).href : null;
}
async function launch() {
  const puppeteer = createRequire('/usr/src/app/package.json')('puppeteer-core');
  return puppeteer.launch({executablePath:'/usr/bin/google-chrome', headless:false,
    userDataDir:'/data/profile', timeout:20000,
    args:['--disable-dev-shm-usage', '--disable-quic', '--disable-background-networking',
      '--proxy-server=http://127.0.0.1:8127', '--proxy-bypass-list=<-loopback>']});
}
async function load(command) {
  if (!allowed(command.url, command, true)) return {state:'failed'};
  if (!browser?.connected) browser = await launch();
  const page = await browser.newPage();
  return loadPage(command, page);
}
async function loadPage(command, page) {
  let refused = false;
  try {
    await page.setJavaScriptEnabled(false);
    await page.setBypassServiceWorker(true);
    await page.setRequestInterception(true);
    const session = await page.createCDPSession();
    // Cross-origin redirect checks must happen before TLS follows the next request.
    page.on('request', async request => {
      try {
        if (request.method() !== 'GET' || !allowed(request.url(), command, request.isNavigationRequest()) ||
            (!request.isNavigationRequest() && ['script','stylesheet','font','image','media','other'].includes(request.resourceType()))) {
          if (request.isNavigationRequest()) refused = true;
          await request.abort(); return;
        }
        const host = new URL(request.url()).hostname;
        const at = Math.max(Date.now(), next.get(host) || 0);
        next.set(host, at + (command.wikis.includes(host) ? 1000 : 300));
        await new Promise(resolve => setTimeout(resolve, Math.max(0, at - Date.now())));
        await request.continue();
      } catch { refused = true; await request.abort().catch(() => {}); }
    });
    await session.send('Network.enable');
    // Each response is additionally limited by the pinned CONNECT proxy's byte budget.
    const response = await page.goto(command.url, {waitUntil:'domcontentloaded', timeout:20000});
    if (!response || refused) return {state:'failed'};
    if (challenged(response.status(), response.headers(), '')) return {state:'challenged'};
    if (response.status() === 429) return {state:'rate_limited'};
    if (command.kind === 'image') {
      if (response.status() !== 200 || !response.headers()['content-type']?.startsWith('image/')) {
        const html = await page.content();
        if (challenged(response.status(), response.headers(), html)) return {state:'challenged'};
        return {state:response.status() === 404 ? 'empty' : 'failed'};
      }
      const data = await response.buffer();
      if (!data.length || data.length > MAX_IMAGE) return {state:'failed'};
      return {state:'ok', url:page.url(), data:data.toString('base64')};
    }
    const html = await page.content();
    if (challenged(response.status(), response.headers(), html)) return {state:'challenged'};
    if (response.status() === 404) return {state:'empty'};
    if (response.status() !== 200 || Buffer.byteLength(html) > MAX_PAGE) return {state:'failed'};
    const url = page.url();
    if (['goodreads','lexicanum_search'].includes(command.kind)) return {state:'ok', html, url};
    const canonical = await page.$eval('link[rel="canonical"]', e => e.href).catch(() => url);
    if (!allowed(canonical, command, true) || !new URL(canonical).pathname.startsWith('/wiki/')) return {state:'failed'};
    const src = await page.evaluate(() => {
      const tables = [...document.querySelectorAll('#mw-content-text table')];
      const table = tables.find(t => /Authors?/.test(t.innerText));
      return [...(table?.querySelectorAll('a.image img') || [])]
        .map(img => img.getAttribute('src'))
        .find(src => src && !/\/Book2\.jpg(?:\/|$)/i.test(src)) || null;
    });
    const cover_url = src ? original(src, canonical) : null;
    const title = decodeURIComponent(new URL(canonical).pathname.slice('/wiki/'.length));
    const exportUrl = new URL('/mediawiki/index.php', canonical);
    exportUrl.search = new URLSearchParams({title:'Special:Export/' + title, curonly:'1'}).toString();
    const exported = await page.goto(exportUrl.href, {waitUntil:'domcontentloaded', timeout:20000});
    if (!exported || refused) return {state:'failed'};
    const xml = await exported.text();
    if (challenged(exported.status(), exported.headers(), xml)) return {state:'challenged'};
    if (exported.status() !== 200 || Buffer.byteLength(xml) > MAX_PAGE) return {state:'failed'};
    return {state:'ok', html, url:canonical, xml, cover_url};
  } finally { await page.close().catch(() => {}); }
}
if (require.main === module) {
  const lines = readline.createInterface({input:process.stdin});
  let tail = Promise.resolve();
  lines.on('line', line => { tail = tail.then(async () => {
    let result;
    try { result = await load(JSON.parse(line)); }
    catch (error) { result = {state:error.name === 'TimeoutError' ? 'timed_out' : 'failed'}; }
    process.stdout.write(JSON.stringify(result) + '\n');
  }); });
  process.on('SIGTERM', async () => { if (browser) await browser.close(); process.exit(0); });
}
module.exports = {allowed, challenged, original, launch, loadPage};
