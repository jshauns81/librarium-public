const {test} = require('node:test');
const assert = require('node:assert/strict');
const {allowed, challenged, original} = require('../services/source-browser/browser.cjs');
const driver = require('../services/source-browser/browser.cjs');
const command = {url:'https://wh40k.lexicanum.com/wiki/Novel', kind:'lexicanum', wikis:['wh40k.lexicanum.com'], images:['i.gr-assets.com'], namespaces:['special','file','user']};
test('redirects and subresources remain on the selected wiki and read-only paths', () => {
  assert.equal(allowed(command.url, command, true), true);
  assert.equal(allowed('https://wh40k.lexicanum.com/wiki/Novel:_The_Sequel', command, true), true);
  for (const url of ['https://whfb.lexicanum.com/wiki/Novel', 'https://wh40k.lexicanum.com/wiki/Novel?action=edit', 'https://wh40k.lexicanum.com/wiki/Special:UserLogin', 'http://wh40k.lexicanum.com/wiki/Novel', 'https://127.0.0.1/wiki/Novel'])
    assert.equal(allowed(url, command, true), false);
  assert.equal(allowed('https://wh40k.lexicanum.com/mediawiki/index.php?title=Special%3AExport%2FNovel&curonly=1', command, true), true);
});
test('challenge content is refused without running scripts or solving it', () => {
  assert.equal(challenged(403, {}, '<title>Just a moment...</title>'), true);
  assert.equal(challenged(200, {'cf-mitigated':'challenge'}, 'anything'), true);
  assert.equal(challenged(200, {}, '<h1>Novel</h1>'), false);
});
test('wiki thumbnail becomes the same-wiki original', () => {
  assert.equal(original('/mediawiki/images/thumb/a/ab/Novel.jpg/200px-Novel.jpg', command.url), 'https://wh40k.lexicanum.com/mediawiki/images/a/ab/Novel.jpg');
});
test('nonstandard thumbnail routes never claim to be originals', () => {
  assert.equal(original('/custom/thumb/Novel.jpg', command.url), null);
  assert.equal(original('/mediawiki/images/thumb/7/7e/Book2.jpg/60px-Book2.jpg', command.url), null);
});
test('Goodreads book navigation accepts known search parameters only', () => {
  const goodreads={...command,kind:'goodreads',url:'https://www.goodreads.com/search?q=Novel'};
  assert.equal(allowed('https://www.goodreads.com/book/show/123.Novel?from_search=true&from_srp=true&qid=abc&rank=1',goodreads,true),true);
  for (const suffix of ['?action=edit','?unknown=','/other'])
    assert.equal(allowed('https://www.goodreads.com/book/show/123.Novel'+suffix,goodreads,true),false);
});

function pageFixture({challenge=false, canonical=null, status=200, headers={}, html='<h1>Novel</h1>'}={}) {
  let handler;
  const visited=[];
  const page={
    visited, closed:false,
    async setJavaScriptEnabled(value){assert.equal(value,false);},
    async setBypassServiceWorker(value){assert.equal(value,true);},
    async setRequestInterception(value){assert.equal(value,true);},
    async createCDPSession(){return {send:async()=>{}};},
    on(event,callback){if(event==='request')handler=callback;},
    async goto(url){visited.push(url);await handler({method:()=> 'GET',url:()=>url,isNavigationRequest:()=>true,continue:async()=>{},abort:async()=>{throw Error('refused');}});return {status:()=>challenge?403:status,headers:()=>headers,text:async()=>'<mediawiki>current XML</mediawiki>'};},
    async content(){return challenge?'<title>Just a moment...</title>':html;},
    url:()=>command.url,
    async $eval(){if(canonical)return canonical;throw Error('missing canonical');},
    async evaluate(){return '/mediawiki/images/thumb/a/ab/Novel.jpg/200px-Novel.jpg';},
    async close(){page.closed=true;},
  };
  return page;
}
test('current XML uses GET export and falls back to current URL without a canonical link', async()=>{
  const page=pageFixture();
  const result=await driver.loadPage(command,page);
  assert.equal(result.state,'ok');assert.equal(result.url,command.url);
  assert.equal(result.xml,'<mediawiki>current XML</mediawiki>');
  const url=new URL(page.visited[1]);
  assert.equal(url.searchParams.get('title'),'Special:Export/Novel');
  assert.equal(url.searchParams.get('curonly'),'1');
  assert.equal(result.cover_url,'https://wh40k.lexicanum.com/mediawiki/images/a/ab/Novel.jpg');
  assert.equal(page.closed,true);
});
for (const kind of ['goodreads','image','lexicanum']) {
  for (const [status, headers, html, state] of [
    [404, {}, 'Not found', 'empty'],
    [500, {}, 'Server error', 'failed'],
    [200, {'content-type':'text/html'}, 'Invalid image response', kind === 'image' ? 'failed' : 'ok'],
    [403, {}, 'Forbidden', 'challenged'],
    [503, {'cf-mitigated':'challenge'}, 'Checking', 'challenged'],
    [503, {}, '<title>Just a moment...</title>', 'challenged'],
  ]) {
    test(`${kind}: HTTP ${status} ${html} reports ${state}`, async () => {
      const page=pageFixture({status,headers,html});
      const url=kind === 'goodreads' ? 'https://www.goodreads.com/search?q=Novel' : command.url;
      assert.equal((await driver.loadPage({...command,kind,url}, page)).state,state);
      assert.equal(page.closed,true);
    });
  }
}
test('a challenge ends the article attempt before any export and closes the page',async()=>{
  const page=pageFixture({challenge:true});
  assert.deepEqual(await driver.loadPage(command,page),{state:'challenged'});
  assert.equal(page.visited.length,1);assert.equal(page.closed,true);
});
test('wiki search admits only bounded fulltext GETs on the selected host', () => {
  const url='https://wh40k.lexicanum.com/mediawiki/index.php?title=Special%3ASearch&search=Novel+Writer&fulltext=1&limit=5&ns0=1';
  const search={...command,kind:'lexicanum_search',url};
  assert.equal(allowed(url,search,true),true);
  for(const suffix of ['&action=edit','&limit=500','&search=Other','&redirect=https://example.org']) assert.equal(allowed(url+suffix,search,true),false);
  assert.equal(allowed(url.replace('wh40k.','whfb.'),search,true),false);
  assert.equal(allowed(command.url,search,true),false);
});
