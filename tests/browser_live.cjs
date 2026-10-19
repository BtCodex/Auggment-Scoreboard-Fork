/* Isolated mocked integration: run tests/serve_qc.py first. No device access. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({executablePath:process.env.QC_CHROMIUM || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const context = await browser.newContext();
  await context.route('**/*',route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  const page = await context.newPage(), errors = [], base = 'http://127.0.0.1:5002';
  page.on('pageerror',error => errors.push(error.message));
  await context.request.post(base+'/login',{form:{username:'admin',password:'root'}});
  const save = async data => assert.equal((await context.request.post(base+'/api/settings',{data})).status(),200);
  await save({device_mode:'server',port:5002,display_mode:'hybrid',header_visibility:'auto',clock_format:'24h',
   show_time_bar:true,show_title_bar:true,show_logo_slide:false,football_display:'both',slide_duration:3600});
  const before = await (await context.request.get(base+'/api/settings')).json();
  await page.setViewportSize({width:390,height:844});
  await page.goto(base+'/settings'); await page.waitForFunction(()=>settingsReady);
  await page.locator('#show_title_bar').uncheck();
  assert.equal(await page.locator('#header_visibility').inputValue(),'always');
  await page.locator('header .btn-save').click();
  await page.waitForFunction(()=>document.querySelector('#settings-message').textContent.includes('Saved.'));
  await page.reload();await page.waitForFunction(()=>settingsReady);
  assert.equal(await page.locator('#show_title_bar').isChecked(),false);
  assert.equal(await page.locator('#show_time_bar').isChecked(),true);
  assert.equal(await page.locator('#clock_format').inputValue(),'24h');
  const after = await (await context.request.get(base+'/api/settings')).json();
  for (const key of ['teams','leagues']) assert.deepEqual([...after[key]].sort(),[...before[key]].sort());
  for (const key of ['colors','show_logo_slide','clock_format']) assert.deepEqual(after[key],before[key]);
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  console.log('PASS phone switches save/reload independently, select persistent header, retain favorites/colors/clock');

  const original = await (await context.request.get(base+'/api/data')).json();
  const fixture = JSON.parse(JSON.stringify(original));
  fixture.specials=[];fixture.show_logo_slide=false;fixture.slide_duration=3600;fixture.header_visibility='always';
  let fail = false;
  await page.route('**/api/data',route=> fail ? route.abort() : route.fulfill({json:fixture}));
  await page.goto(base+'/');await page.waitForSelector('.card');
  for (const mode of ['scoreboard','hybrid','ticker']) for (const format of ['12h','24h','hidden']) {
   for (const title of [true,false]) for (const time of [true,false]) {
    Object.assign(fixture,{display_mode:mode,clock_format:format,show_title_bar:title,show_time_bar:time});
    await page.evaluate(()=>updateData());
    const state=await page.evaluate(()=>({title:!document.querySelector('#display-name').hidden,
     time:!document.querySelector('#top-clock').hidden,separator:!document.querySelector('#header-sep').hidden,
     weather:!document.querySelector('#weather').hidden,collapsed:document.body.classList.contains('header-hidden'),
     visible:document.querySelector('#main-header').getAttribute('aria-hidden')==='false'}));
    const effectiveTime=time&&format!=='hidden';
    assert.deepEqual(state,{title,time:effectiveTime,separator:title&&effectiveTime,weather:title,
     collapsed:!title&&!effectiveTime,visible:title||effectiveTime});
    assert.equal(await page.locator('#display-name').isVisible(),title);
    assert.equal(await page.locator('#weather').isVisible(),title);
    assert.equal(await page.locator('#top-clock').isVisible(),effectiveTime);
    if (!title && !effectiveTime) assert.equal(await page.locator('#main-header').evaluate(el=>el.getBoundingClientRect().height),0);
   }
  }
  console.log('PASS 36 title/time/clock combinations across all display modes without reload');

  Object.assign(fixture,{display_mode:'hybrid',show_title_bar:true,show_time_bar:true,clock_format:'12h'});
  const card = JSON.parse(JSON.stringify(original.teams[0]));
  card.game_state='live';card.color_state='live';card.is_pre=false;card.status='Q3 4:20';card.live_detail_ttl_seconds=90;
  card.football_tracker={possession:'home',team:'TA&M',position:92,direction:'right',label:'1st & Goal at ALA 8',
   quarter:'Q3',clock:'4:20',red_zone:true,goal_to_go:true};
  card.baseball_tracker=null;fixture.teams=[card];
  for (const sport of ['football/college-football','football/nfl','baseball/mlb']) {
   card.league_path=sport;card.league_label=sport==='baseball/mlb'?'MLB':'FOOTBALL';
   if (sport==='football/nfl') {
    card.home_name='HOU';card.away_name='DAL';card.home_rank=null;card.away_rank=null;
    Object.assign(card.football_tracker,{team:'HOU',label:'1st & Goal at DAL 8'});
   }
   if (sport==='baseball/mlb') {
    card.football_tracker=null;card.away_name='HOU';card.home_name='NYY';card.away_rank=null;card.home_rank=null;
    card.home_record='101-61';card.away_record='90-72';
    card.home_score='3';card.away_score='4';card.status='Bottom 10th';
    card.baseball_tracker={bases:{first:true,second:false,third:true},inning:10,half:'bottom',outs:2,away_score:'4',home_score:'3'};
    card.period_scores={labels:Array.from({length:10},(_,i)=>String(i+1)),home:[0,0,0,0,0,0,1,2,0,null],away:[0,0,0,0,0,0,0,0,3,1],
     totals:{home:{score:'3',hits:8,errors:0},away:{score:'4',hits:10,errors:1}}};
   }
   await page.evaluate(()=>updateData());
   assert.equal(await page.locator('.live-tracker').count(),1);
   for (const [width,height] of [[360,800],[390,844],[844,390],[1080,1920],[1920,1080],[2560,1080]]) {
    await page.setViewportSize({width,height});
    const overflow=await page.evaluate(()=>{
     const card=document.querySelector('.slide.active .card').getBoundingClientRect();
     const details=[...document.querySelectorAll('.slide.active .team-logo-lockup,.slide.active .team-logo,.slide.active .team-abbr,.slide.active .team-record,.slide.active .score-display,.slide.active .live-tracker,.slide.active .period-breakdown')];
     return details.filter(el=>{
      const r=el.getBoundingClientRect();return r.width>0&&(r.left<card.left-1||r.right>card.right+1||r.top<card.top-1||r.bottom>card.bottom+1);
     }).map(el=>el.className);
    });
    assert.deepEqual(overflow,[],`${sport} overflow ${width}x${height}: ${overflow}`);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    if ([390,1920,2560].includes(width)) await page.screenshot({path:`/tmp/scoreboard-live-${sport==='baseball/mlb'?'mlb':sport==='football/nfl'?'nfl':'cfb'}-${width}.png`});
   }
   for (const state of ['scheduled','halftime','final','postponed','canceled']) {
    card.game_state=state;await page.evaluate(()=>updateData());
    assert.equal(await page.locator('.live-tracker').count(),0,state);
    assert.equal(await page.locator('.period-table').count(),1);
   }
   card.game_state='live';
  }
  console.log('PASS CFB/NFL/MLB live widgets + periods/logos at six sizes; inactive states hide only widgets');
  await page.evaluate(()=>updateData());
  const scoreText=await page.locator('.score-display').textContent();
  fail=true;await page.evaluate(()=>updateData());
  assert.equal(await page.locator('.live-tracker').count(),0);
  assert.equal(await page.locator('.score-display').textContent(),scoreText);
  assert.equal(await page.locator('.period-table').count(),1);
  fail=false;await page.evaluate(()=>updateData());
  assert.equal(await page.locator('.live-tracker').count(),1);
  card.live_detail_ttl_seconds=.3;await page.evaluate(()=>updateData());
  await page.waitForFunction(()=>!document.querySelector('.live-tracker'),{},{timeout:3000});
  assert.equal(await page.locator('.period-table').count(),1);
  card.live_detail_ttl_seconds=90;card.baseball_tracker.bases.first='unknown';await page.evaluate(()=>updateData());
  assert.equal(await page.locator('.live-tracker').count(),0);
  assert.equal(await page.locator('.period-table').count(),1);
  console.log('PASS API outage hides transient state, retains main scores, recovers and expires without fetch; malformed bases hide widget');
  assert.deepEqual(errors,[]);console.log('PASS zero uncaught JavaScript errors');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
