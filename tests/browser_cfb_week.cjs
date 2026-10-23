/* Isolated complete-week rotation regression. Run tests/serve_qc.py first.
 * All 45 scorecards below are SYNTHETIC, not an asserted ESPN schedule. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const CFB = 'football/college-football';

function syntheticGame(index) {
 const state = ['scheduled', 'live', 'final'][index % 3];
 const kickoff = new Date(Date.UTC(2026, 9, 24, 17, Math.floor(index / 5) * 45)).toISOString();
 const names = index === 0 ? ['TA&M', 'ALA'] : index === 17 ? ['MISS', 'TEX'] : index === 44 ? ['ND', 'G5'] : ['A'+index, 'H'+index];
 return {league_path:CFB,league_label:'NCAA Football',event_id:String(700000000+index),kickoff_iso:kickoff,
  away_name:names[0],home_name:names[1],away_score:state==='scheduled'?'—':'14',home_score:state==='scheduled'?'—':'21',
  away_logo:'',home_logo:'',away_rank:null,home_rank:null,away_record:'4-2',home_record:'5-1',
  away_is_fav:index===0,home_is_fav:index===0,color_state:state==='scheduled'?'pre':state,
  game_state:state,is_pre:state==='scheduled',status:state==='live'?'Q3 4:20':state==='final'?'Final':'Scheduled',
  local_time:'12:00 PM',winner:state==='final'?'home':null,period_scores:null,football_tracker:null,baseball_tracker:null};
}

(async () => {
 const browser = await chromium.launch({executablePath:process.env.QC_CHROMIUM || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const context = await browser.newContext();
  await context.route('**/*',route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  const page = await context.newPage(), errors = [], base = 'http://127.0.0.1:5002';
  page.on('pageerror',error => errors.push(error.message));
  await context.request.post(base+'/login',{form:{username:'admin',password:'root'}});
  const save = async data => assert.equal((await context.request.post(base+'/api/settings',{data})).status(),200);
  await save({device_mode:'server',port:5002,city:'',display_mode:'scoreboard',cfb_coverage:'all_power5',
   scorecard_filter:'both',scorecard_include_completed:true,
   header_visibility:'always',clock_format:'12h',show_time_bar:true,show_title_bar:true,show_logo_slide:false,
   football_display:'both',leagues:[CFB],teams:[CFB+':TA&M'],slide_duration:3600,transition_duration_ms:0,specials:[]});
  const before = await (await context.request.get(base+'/api/settings')).json();
  await page.setViewportSize({width:390,height:844});
  await page.goto(base+'/settings');await page.waitForFunction(()=>settingsReady);
  for (const coverage of ['favorites','all_power5']) {
   await page.locator('#cfb_coverage').selectOption(coverage);
   await page.locator('header .btn-save').click();
   await page.waitForFunction(coverage=>currentSettings.cfb_coverage===coverage,coverage);
   await page.reload();await page.waitForFunction(()=>settingsReady);
   assert.equal(await page.locator('#cfb_coverage').inputValue(),coverage);
  }
  for (const [filter,completed] of [['live',false],['upcoming',true],['both',true]]) {
   await page.locator('#scorecard_filter').selectOption(filter);
   await page.locator('#scorecard_include_completed').setChecked(completed);
   await page.locator('header .btn-save').click();
   await page.waitForFunction(([filter,completed])=>currentSettings.scorecard_filter===filter&&currentSettings.scorecard_include_completed===completed,[filter,completed]);
   await page.reload();await page.waitForFunction(()=>settingsReady);
   assert.equal(await page.locator('#scorecard_filter').inputValue(),filter);
   assert.equal(await page.locator('#scorecard_include_completed').isChecked(),completed);
  }
  const saved = await (await context.request.get(base+'/api/settings')).json();
  assert.deepEqual([...saved.teams].sort(),[...before.teams].sort());
  const normalizedColors = value => Object.fromEntries(Object.entries(value).map(([key,color])=>[key,typeof color==='string'?color.toLowerCase():color]));
  assert.deepEqual(normalizedColors(saved.colors),normalizedColors(before.colors));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:'/tmp/cfb-week-phone.png',fullPage:true});
  console.log('PASS phone coverage/live/upcoming/both/completed preferences save/reload without changing favorites or colors');

  const fixture = await (await context.request.get(base+'/api/data')).json();
  const cards = Array.from({length:45},(_,index)=>syntheticGame(index));
  // Reverse kickoff order and tie order to test deterministic presentation sorting.
  fixture.teams=[...cards].reverse();fixture.ticker_parts=[];fixture.races=[];fixture.golf=[];fixture.specials=[];fixture.local_schedule_items=[];
  Object.assign(fixture,{cfb_coverage:'all_power5',scorecard_filter:'both',scorecard_include_completed:true,show_logo_slide:false,display_mode:'scoreboard',
   slide_duration:3600,transition_duration_ms:0,browser_refresh_seconds:180,
   slide_playlist:[{type:'team',key:CFB+':ND'},{type:'team',key:CFB+':ALA'},
    {type:'team',key:CFB+':TA&M'},{type:'team',key:CFB+':ND'}]});
  let fail = false;
  await page.route('**/api/data',route=>fail?route.abort():route.fulfill({json:fixture}));
  await page.goto(base+'/');
  await page.waitForFunction(()=>document.querySelectorAll('#main-stage .slide[data-event-id]').length===45);
  const ids = () => page.locator('#main-stage .slide').evaluateAll(elements=>elements.map(el=>el.dataset.eventId));
  const activeId = () => page.locator('#main-stage .slide.active').getAttribute('data-event-id');
  const expected = cards.map(card=>card.event_id);
  assert.deepEqual(await ids(),expected);
  assert.equal(new Set(await ids()).size,45);
  assert.ok((await page.locator('#main-stage').textContent()).includes('TEX'));
  assert.deepEqual(await page.locator('#main-stage .slide').evaluateAll(elements=>elements.map(el=>el.dataset.slideKey)),
   expected.map(id=>'team:'+CFB+':'+id));
  await page.setViewportSize({width:1920,height:1080});
  await page.screenshot({path:'/tmp/cfb-week-rotation.png'});
  console.log('PASS all 45 games appear once in kickoff/tie order despite favorite playlist duplicates and unlisted Texas');

  // Advance the real slideshow routine through the whole slate. Refreshes must
  // not reset its index or replace the stable outer slide nodes.
  const visited = [];
  for (let index=0;index<45;index++) {
   visited.push(await activeId());
   if (index%4===0) {
    await page.evaluate(()=>{window.__cfbActiveNode=document.querySelector('#main-stage .slide.active');window.__cfbFirstNode=document.querySelector('#main-stage .slide');});
    const priorId=await activeId();
    fixture.teams[index].home_score=String(21+index);
    fixture.teams[index].game_state='final';fixture.teams[index].color_state='final';fixture.teams[index].is_pre=false;fixture.teams[index].status='Final';
    await page.evaluate(()=>updateData());
    assert.equal(await activeId(),priorId);
    assert.ok(await page.evaluate(()=>window.__cfbActiveNode===document.querySelector('#main-stage .slide.active') && window.__cfbFirstNode===document.querySelector('#main-stage .slide')));
    assert.deepEqual(await ids(),expected);
   }
   await page.evaluate(()=>{if(slideTimer) clearTimeout(slideTimer);advanceSlide();});
  }
  assert.deepEqual(visited,expected);
  assert.equal(await activeId(),expected[0]);
  // A provider abbreviation correction must not create a new game identity.
  fixture.teams[2].away_name='CORRECTED';await page.evaluate(()=>updateData());
  assert.deepEqual(await ids(),expected);
  assert.equal(await activeId(),expected[0]);
  console.log('PASS full final-to-first traversal with 12 mid-rotation score/status refreshes and stable slide identity');

  fail=true;await page.evaluate(()=>updateData());
  assert.deepEqual(await ids(),expected);assert.equal(await activeId(),expected[0]);
  assert.equal(await page.locator('#connection-status').isVisible(),true);
  fail=false;await page.evaluate(()=>updateData());
  assert.deepEqual(await ids(),expected);
  console.log('PASS temporary API failure retains the entire current rotation and recovery preserves position');

  fixture.cfb_coverage='favorites';fixture.teams=[cards[0],cards[44]];
  await page.evaluate(()=>updateData());
  assert.deepEqual(await ids(),[cards[44].event_id,cards[0].event_id]);
  assert.equal(new Set(await ids()).size,2);
  console.log('PASS legacy favorites mode retains explicit playlist ordering without duplicate cards');

  fixture.cfb_coverage='all_power5';fixture.teams=[...cards].reverse();fixture.slide_duration=1;
  await page.evaluate(()=>updateData());
  // Move to the last game with the application's own advance function, then
  // let a genuine timer tick exercise wraparound (no mocked clock).
  await page.evaluate(()=>{
   const slides=[...document.querySelectorAll('#main-stage .slide')];
   while(!slides[slides.length-1].classList.contains('active')) {
    if(slideTimer)clearTimeout(slideTimer);advanceSlide();
   }
  });
  assert.equal(await activeId(),expected[44]);
  await page.waitForFunction(id=>document.querySelector('#main-stage .slide.active')?.dataset.eventId===id,expected[0],{timeout:2500});
  assert.deepEqual(await ids(),expected);
  fixture.teams=[];fixture.display_mode='hybrid';fixture.scorecard_filter='live';fixture.scorecard_include_completed=false;
  fixture.ticker_parts=[{label:'NFL',games:[{league_path:'football/nfl',event_id:'900000000',
   away:'HOU',home:'TEN',away_score:'17',home_score:'14',away_logo:'',home_logo:'',
   color_state:'live',game_state:'live',status:'Q3 4:20',winner:null}]}];
  await page.evaluate(()=>updateData());
  assert.equal(await page.locator('#main-stage .card').count(),0);
  assert.equal(await page.locator('#main-stage .empty-state').isVisible(),true);
  assert.ok((await page.locator('#main-stage .empty-state').textContent()).trim().length>10);
  assert.equal(await page.locator('#main-footer').isVisible(),true);
  assert.ok((await page.locator('#ticker-text').textContent()).includes('HOU'));
  assert.deepEqual(errors,[]);
  console.log('PASS actual timer wraps last-to-first; filtered empty main stays useful with independent visible ticker; zero uncaught JavaScript errors');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
