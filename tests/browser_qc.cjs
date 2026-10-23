/* Optional development-only test: npm install --prefix /tmp/scoreboard-qc playwright
 * Run serve_qc.py first, then NODE_PATH=/tmp/scoreboard-qc/node_modules node tests/browser_qc.cjs.
 */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({executablePath: process.env.QC_CHROMIUM || '/usr/bin/chromium', headless:true, args:['--no-sandbox']});
 try {
 const context = await browser.newContext();
 await context.route('**/*', route => {
   const url = new URL(route.request().url());
   if (url.hostname !== '127.0.0.1') return route.abort();
   return route.continue();
 });
 const page = await context.newPage();
 const errors = [];
 page.on('pageerror', e => errors.push(e.message));
 const base = 'http://127.0.0.1:5002';
 await context.request.post(base+'/login', {form:{username:'admin', password:'root'}});
 // Reset only this isolated fixture so repeated browser runs are independent.
 const baseline=await context.request.post(base+'/api/settings',{data:{
   device_mode:'server',port:5002,display_name:'AGGIE GAMEDAY',clock_format:'12h',
   cfb_coverage:'favorites',scorecard_filter:'both',scorecard_include_completed:true,
   display_mode:'hybrid',header_visibility:'auto',show_time_bar:true,show_title_bar:true,show_logo_slide:true,football_priority:true,football_display:'both',timezone:'America/Chicago',
   teams:['football/college-football:TA&M','football/nfl:HOU'],leagues:['football/college-football','football/nfl'],
   slide_duration:2,logo_slide_duration:2,transition_duration_ms:500,ticker_speed:120,
   local_schedule:{rss_feeds:[],items:[],home_team_keywords:[]},
   specials:[{uid:'test1',type:'text',title:'First',enabled:true},{uid:'test2',type:'text',title:'Second',enabled:true}]
 }});
 assert.equal(baseline.status(),200);
 const testLogo=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
 assert.equal((await context.request.post(base+'/api/upload_logo',{multipart:{logo:{name:'qc.png',mimeType:'image/png',buffer:testLogo}}})).status(),200);

 await page.goto(base+'/settings');
 await page.waitForFunction(() => settingsReady && currentSettings.teams?.length === 2);
 for (const [width,height] of [[360,800],[390,844],[844,390],[1080,1920],[1920,1080],[2560,1080]]) {
   await page.setViewportSize({width,height});
   const overflow = await page.evaluate(() => ({doc:document.documentElement.scrollWidth, width:innerWidth}));
   assert.ok(overflow.doc <= width+1, `settings overflow at ${width}: ${JSON.stringify(overflow)}`);
   console.log(`PASS settings width ${width}x${height}`);
 }
 await page.setViewportSize({width:390,height:844});
 for (const [mode,paths] of [['cfb',['football/college-football']],['nfl',['football/nfl']],
                            ['weekly',null],['both',['football/college-football','football/nfl']]]) {
   await page.locator('#football_display').selectOption(mode);
   await page.locator('header .btn-save').click();
   await page.waitForFunction(() => document.querySelector('#settings-message').textContent.includes('Saved.'));
   await page.reload();
   await page.waitForFunction(() => settingsReady);
   assert.equal(await page.locator('#football_display').inputValue(),mode);
   const slate=await (await context.request.get(base+'/api/data')).json();
   assert.equal(slate.football_display,mode);
   if (paths) {
     assert.deepEqual([...new Set(slate.teams.map(team=>team.league_path))].sort(),[...paths].sort());
     assert.deepEqual([...new Set(slate.ticker_parts.flatMap(part=>part.games.map(game=>game.league_path)))].sort(),[...paths].sort());
   }
 }
 console.log('PASS phone football mode saves, reloads and filters cards/ticker without losing favorites');
 await page.evaluate(()=>setMode('kiosk'));
 assert.ok(await page.locator('#kiosk-setup-section').isVisible());
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1));
 await page.evaluate(()=>setMode('server'));
 console.log('PASS kiosk setup is phone accessible');
 await page.locator('#clock_format').selectOption('24h');
 await page.locator('#show_logo_slide').uncheck();
 await page.locator('header .btn-save').click();
 await page.waitForTimeout(150);
 assert.equal((await context.request.get(base+'/api/settings')).status(),200);
 const saved=await (await context.request.get(base+'/api/settings')).json();
 assert.equal(saved.clock_format,'24h'); assert.equal(saved.show_logo_slide,false);
 // Touch alternatives to all three drag-only lists.
 assert.ok(await page.locator('#playlist-chips .move-controls button').count() > 0);
 await page.locator('#playlist-chips .move-controls button[aria-label="Move later"]').first().click();
 await page.locator('#fav-grid .move-controls button[aria-label="Move later"]').first().click();
 await page.locator('.special-item .move-controls button[aria-label="Move later"]').first().click();
 console.log('PASS phone save and playlist/favorite/special reorder buttons');
 await page.goto(base+'/');
 await page.waitForSelector('.team-abbr');
 assert.equal(await page.locator('#logo-slide').count(),0);
 assert.match(await page.locator('#top-clock').textContent(),/^\d{2}:\d{2}$/);
 assert.ok((await page.locator('.team-abbr').allTextContents()).some(x=>x==='TA&M'));
 assert.ok(await page.locator('.team-logo-lockup.ranked img + .team-rank-badge[aria-label="AP ranking 7"]').count()>0);
 assert.ok(await page.locator('#ticker-text .tick-logo + .tick-rank-badge[aria-label="AP ranking 7"]').count()>0);
 assert.equal(await page.locator('.team-abbr').filter({hasText:'#7'}).count(),0);
 assert.ok((await page.locator('.team-rank-badge').allTextContents()).every(text=>text==='#7'));
 console.log('PASS verified AP rank beside logos with no duplicate name prefix or unranked badge');
 for (const [width,height] of [[390,844],[844,390],[1080,1920],[1920,1080],[2560,1080]]) {
   await page.setViewportSize({width,height});
   assert.equal(await page.locator('.slide.active').count(),1);
   const bounds = await page.locator('.slide.active').boundingBox();
   assert.ok(bounds && bounds.width > 0 && bounds.height > 0);
   console.log(`PASS display ${width}x${height}`);
 }
 await page.setViewportSize({width:1920,height:1080});
 const firstKey = await page.locator('.slide.active').getAttribute('data-slide-key');
 await page.waitForTimeout(2300);
 assert.notEqual(await page.locator('.slide.active').getAttribute('data-slide-key'), firstKey);
 console.log('PASS automatic slide rotation');
 await page.route('**/api/data', async route => {
   const response=await route.fetch(); const data=await response.json();
   data.teams[0].home_score='27';
   data.ticker_parts[0].games[0].home_score='27';
   await route.fulfill({response,json:data});
 });
 await page.evaluate(()=>updateData());
 assert.ok(await page.locator('.card.flash').count()>0);
 assert.ok(await page.locator('#ticker-text .flash-yellow').count()>0);
 await page.unroute('**/api/data');
 await page.evaluate(()=>updateData());
 console.log('PASS score changes highlight both cards and ticker');
 // Preserve the current DOM across HTTP/JSON/network failures, then recover.
 await page.evaluate(() => clearTimeout(slideTimer));
 await page.waitForTimeout(700);
 const before = await page.locator('#main-stage').innerHTML();
 await page.route('**/api/data', route => route.fulfill({status:503,body:'offline'}));
 await page.evaluate(() => updateData());
 assert.equal(await page.locator('#main-stage').innerHTML(),before);
 await page.unroute('**/api/data');
 await page.route('**/api/data', route => route.fulfill({contentType:'application/json', body:'{"error":"bad payload"}'}));
 await page.evaluate(() => updateData());
 assert.equal(await page.locator('#main-stage').innerHTML(),before);
 await page.unroute('**/api/data');
 await page.route('**/api/data', route=>route.abort());
 await page.evaluate(()=>updateData());
 assert.equal(await page.locator('#main-stage').innerHTML(),before);
 await page.unroute('**/api/data');
 await page.evaluate(()=>updateData());
 assert.ok(await page.locator('.team-abbr').count()>0);
 console.log('PASS browser outage retention and recovery');
 // Hidden and default 12h on a full reload, without waiting for a sports refresh.
 await context.request.post(base+'/api/settings',{data:{clock_format:'hidden',show_logo_slide:true}});
 await page.reload(); await page.waitForSelector('#logo-slide');
 assert.equal(await page.locator('#top-clock').isVisible(),false);
 assert.equal(await page.locator('#header-sep').isVisible(),false);
 const logoSrc=await page.locator('#logo-slide img').getAttribute('src');
 await page.evaluate(()=>updateData());
 assert.equal(await page.locator('#logo-slide img').getAttribute('src'),logoSrc);
 await context.request.post(base+'/api/settings',{data:{clock_format:'12h'}});
 await page.reload(); await page.waitForSelector('.team-abbr');
 assert.match(await page.locator('#top-clock').textContent(), / (AM|PM)$/);
 assert.equal(await page.locator('img[src*="placeholder"]').count(),0);
 console.log('PASS hidden/default clock, stable logo URL, no white placeholder');
 // Repeated renders bound DOM and score-history state; no wall-clock soak claim.
 const slideCount=await page.locator('#main-stage .slide').count();
 for(let i=0;i<100;i++) await page.evaluate(()=>updateData());
 assert.equal(await page.locator('#main-stage .slide').count(),slideCount);
 assert.equal(await page.evaluate(()=>Object.keys(previousScores).length),3);
 console.log('PASS 100 repeated refreshes: stable slide count and bounded score history');

 // All display modes apply live, without a page reload.
 const currentUrl = page.url();
 await context.request.post(base+'/api/settings',{data:{display_mode:'ticker'}});
 await page.evaluate(()=>updateData());
 assert.equal(page.url(),currentUrl);
 assert.equal(await page.locator('#main-stage').isVisible(),false);
 assert.equal(await page.locator('#main-header').isVisible(),false);
 assert.equal(await page.locator('#main-footer').isVisible(),true);
 assert.ok(await page.locator('.tick-logo').count()>0);
 await page.setViewportSize({width:2560,height:360});
 await page.screenshot({path:'/tmp/scoreboard-qc-led-ticker.png'});
 await context.request.post(base+'/api/settings',{data:{display_mode:'scoreboard'}});
 await page.evaluate(()=>updateData());
 assert.equal(await page.locator('#main-footer').isVisible(),false);
 assert.equal(await page.evaluate(()=>tickerLoopRAF),null);
 await context.request.post(base+'/api/settings',{data:{display_mode:'hybrid',slide_duration:1,logo_slide_duration:300}});
 await page.evaluate(()=>updateData());
 assert.equal(await page.evaluate(()=>slideInterval),1000);
 assert.equal(await page.evaluate(()=>logoSlideInterval),300000);
 console.log('PASS all three live display modes and full slide-duration range');
 // Settings escaping and safe defaults preserve actual saved content.
 await context.request.post(base+'/api/settings',{data:{specials:[{uid:'unsafe',type:'text',enabled:true,title:'<img src=x onerror="window.qcInjected=1">',body:'Literal <text>'}], local_schedule:{rss_feeds:[{url:'https://example.invalid/news',label:'<img src=x onerror="window.qcInjected=2">',enabled:false}]}}});
 await page.goto(base+'/settings');
 await page.waitForFunction(()=>settingsReady);
 assert.equal(await page.evaluate(()=>window.qcInjected),undefined);
 assert.ok((await page.locator('input[data-field="title"]').inputValue()).includes('<img'));
 await page.locator('.rss-label-input').fill('<img src=x onerror="window.qcInjected=3">');
 assert.equal(await page.evaluate(()=>window.qcInjected),undefined);
 assert.equal(await page.locator('#settings-admin').count(),1);
 const beforeReset=await (await context.request.get(base+'/api/settings')).json();
 await context.request.post(base+'/api/settings/safe-defaults');
 const reset=await (await context.request.get(base+'/api/settings')).json();
 assert.deepEqual(reset.teams,beforeReset.teams);
 assert.deepEqual(reset.specials,beforeReset.specials);
 assert.equal(reset.clock_format,'12h');
 assert.equal(reset.display_mode,'hybrid');
 await page.goto(base+'/');
 await page.waitForSelector('.team-abbr');
 assert.equal(await page.evaluate(()=>window.qcInjected),undefined);
 console.log('PASS stored-text escaping and content-preserving safe timing reset');
 // Removing a logo must leave no blank slide; then test a genuinely empty slate.
 const removal=await context.request.delete(base+'/api/logo'); assert.equal(removal.status(),200);
 await page.evaluate(()=>updateData());
 assert.equal(await page.locator('#logo-slide').count(),0);
 await page.route('**/api/data', async route=>{const response=await route.fetch(); const data=await response.json(); Object.assign(data,{teams:[],races:[],golf:[],specials:[],local_schedule_items:[],ticker_parts:[],show_logo_slide:false}); await route.fulfill({response,json:data});});
 await page.evaluate(()=>updateData());
 assert.equal(await page.locator('#main-stage .slide').count(),1);
 assert.ok((await page.locator('#main-stage').textContent()).toLowerCase().includes('game'));
 assert.equal(await page.locator('#ticker-text .tick-logo').count(),0);
 await page.unroute('**/api/data');
 await page.evaluate(()=>updateData());
 console.log('PASS logo deletion, no blank slides, empty-slate rendering and recovery');
 const offlineFontsPage = await context.newPage();
 let pendingFonts = 0;
 const fontRequests = [];
 await offlineFontsPage.route('https://fonts.googleapis.com/**', route => {
   pendingFonts++;
   const task = new Promise(resolve => setTimeout(resolve, 2000)).then(async () => {
     pendingFonts--; await route.abort();
   });
   fontRequests.push(task); return task;
 });
 await offlineFontsPage.goto(base+'/', {waitUntil:'domcontentloaded'});
 await offlineFontsPage.waitForSelector('.team-abbr', {timeout:1500});
 assert.ok(pendingFonts>0, 'Scoreboard should render while optional remote font is pending');
 await Promise.all(fontRequests);
 await offlineFontsPage.close();
 console.log('PASS score rendering does not wait for unavailable remote fonts');
 assert.deepEqual(errors,[]);
 console.log('PASS zero uncaught JavaScript errors');
 for (const [width,height,name] of [[1920,1080,'landscape'],[1080,1920,'portrait'],[390,844,'phone'],[2560,1080,'ultrawide']]) {
   await page.setViewportSize({width,height});
   await page.evaluate(()=>{document.querySelectorAll('.slide').forEach(el=>el.classList.remove('active')); document.querySelector('.slide[data-slide-key^="team:"]').classList.add('active');});
   const box=await page.locator('.slide.active .card').boundingBox();
   const nameBox=await page.locator('#display-name').boundingBox();
   const clockBox=await page.locator('#top-clock').boundingBox();
   assert.ok(nameBox.x+nameBox.width <= clockBox.x+1, `${name} name overlaps clock`);
   assert.ok(box.x >= -1 && box.y >= -1 && box.x+box.width <= width+1 && box.y+box.height <= height+1, `${name} card out of viewport: ${JSON.stringify(box)}`);
   const contentFits = await page.evaluate(() => {
     const card=document.querySelector('.slide.active .card').getBoundingClientRect();
     return [...document.querySelectorAll('.slide.active .team-block,.slide.active .center-col,.slide.active .score-display,.slide.active .team-abbr,.slide.active .score-part,.slide.active .team-logo-lockup,.slide.active .team-rank-badge')].every(el=>{
       if (!el.getClientRects().length) return true;
       const rect=el.getBoundingClientRect();
       return rect.left>=card.left-1 && rect.right<=card.right+1 && rect.top>=card.top-1 && rect.bottom<=card.bottom+1;
     });
   });
   assert.ok(contentFits, `${name} score/team content overflows card`);
   const originalScores=await page.locator('.slide.active .score-part').allTextContents();
   await page.locator('.slide.active .score-part').evaluateAll(elements=>elements.forEach(el=>el.textContent='137'));
   const largeScoreFits=await page.evaluate(()=>{
     const card=document.querySelector('.slide.active .card').getBoundingClientRect();
     return [...document.querySelectorAll('.slide.active .score-part')].every(el=>{const rect=el.getBoundingClientRect();return rect.left>=card.left-1 && rect.right<=card.right+1;});
   });
   assert.ok(largeScoreFits, `${name} three-digit scores overflow card`);
   await page.locator('.slide.active .score-part').evaluateAll((elements,scores)=>elements.forEach((el,i)=>el.textContent=scores[i]),originalScores);
   await page.screenshot({path:`/tmp/scoreboard-qc-${name}.png`});
 }
 console.log('PASS score cards fit phone, portrait, landscape and ultrawide viewports');
 } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
