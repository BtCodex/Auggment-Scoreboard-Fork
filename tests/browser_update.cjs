/* Run after tests/serve_qc.py. Uses only isolated mock scores/settings. */
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({executablePath:process.env.QC_CHROMIUM || '/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 try {
  const context = await browser.newContext();
  await context.route('**/*',route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
  const page = await context.newPage(), errors = [], base = 'http://127.0.0.1:5002';
  page.on('pageerror',error=>errors.push(error.message));
  await context.request.post(base+'/login',{form:{username:'admin',password:'root'}});
  async function save(data) { assert.equal((await context.request.post(base+'/api/settings',{data})).status(),200); }
  await save({device_mode:'server',port:5002,display_name:'AGGIE GAMEDAY',city:'',display_mode:'hybrid',
   header_visibility:'always',clock_format:'12h',show_time_bar:true,show_title_bar:true,show_logo_slide:false,football_priority:true,football_display:'both',
   teams:['football/college-football:TA&M','football/nfl:HOU'],leagues:['football/college-football','football/nfl'],
   league_conferences:{},conference_filters_version:2,slide_duration:3600,specials:[]});
  await page.setViewportSize({width:390,height:844});
  await page.goto(base+'/settings');
  await page.waitForFunction(()=>settingsReady);
  for (const visibility of ['hidden','auto','always']) {
   await page.locator('#header_visibility').selectOption(visibility);
   await page.locator('header .btn-save').click();
   await page.waitForFunction(()=>document.querySelector('#settings-message').textContent.includes('Saved.'));
   await page.reload(); await page.waitForFunction(()=>settingsReady);
   assert.equal(await page.locator('#header_visibility').inputValue(),visibility);
  }
  console.log('PASS phone header save/reload persistence');
  for (const [league,count] of [['football/college-football',76],['football/nfl',32]]) {
   await page.locator('#team-league-select').selectOption(league);
   await page.waitForFunction(count=>document.querySelectorAll('#team-list .team-check').length===count,count);
   assert.equal(await page.locator('#team-list .team-check').count(),count);
  }
  await page.locator('#team-league-select').selectOption('football/college-football');
  const aggies=page.locator('#team-list .team-check[data-key="football/college-football:TA&M"]');
  await aggies.waitFor();
  assert.ok((await aggies.getAttribute('class')).includes('selected'));
  await aggies.click();
  assert.ok(!(await aggies.getAttribute('class')).includes('selected'));
  await aggies.click();
  assert.ok(await page.evaluate(()=>selectedTeams.includes('football/college-football:TA&M') && !selectedTeams.includes('football/college-football:TA&amp;M')));
  const smu=page.locator('#team-list .team-check[data-key="football/college-football:SMU"]');
  await smu.waitFor(); await smu.click();
  await page.locator('header .btn-save').click();
  await page.waitForFunction(()=>currentSettings.teams.includes('football/college-football:SMU'));
  await page.reload(); await page.waitForFunction(()=>settingsReady);
  assert.ok(await page.evaluate(()=>selectedTeams.includes('football/college-football:SMU')));
  await page.locator('#team-league-select').selectOption('football/college-football');
  await smu.waitFor(); await smu.click(); await page.locator('header .btn-save').click();
  await page.waitForFunction(()=>!currentSettings.teams.includes('football/college-football:SMU'));
  console.log('PASS all 76 CFB/32 NFL choices and phone add/remove SMU');
  await page.goto(base+'/'); await page.waitForSelector('.period-table');
  assert.ok((await page.locator('.team-record').allTextContents()).includes('5-1'));
  assert.ok((await page.locator('.period-table thead').first().textContent()).includes('Q4'));
  assert.ok((await page.locator('.period-table').first().textContent()).includes('—'));
  for (const mode of ['scoreboard','hybrid','ticker']) {
   for (const visibility of ['always','hidden','auto']) {
    await save({display_mode:mode,header_visibility:visibility});
    await page.evaluate(()=>updateData());
    for (const phase of [true,false]) {
     await page.evaluate(phase=>{automaticHeaderVisible=phase;applyHeaderVisibility(headerVisibility);},phase);
     const state=await page.evaluate(()=>({visible:getComputedStyle(document.querySelector('#main-header')).display!=='none' && !document.querySelector('#main-header').classList.contains('hidden'),
      collapsed:document.body.classList.contains('header-hidden'),clock:document.querySelector('#top-clock').textContent,
      footer:document.querySelector('#main-footer').getBoundingClientRect().bottom,height:innerHeight}));
     assert.equal(state.visible,visibility==='always' || (visibility==='auto' && mode!=='ticker' && phase));
     assert.equal(state.collapsed,visibility==='hidden' || (visibility==='auto' && mode==='ticker'));
     assert.match(state.clock,/AM|PM/); assert.ok(state.footer<=state.height+1);
    }
   }
  }
  await save({clock_format:'hidden',header_visibility:'always',display_mode:'hybrid'});
  await page.evaluate(()=>updateData());
  assert.equal(await page.locator('#top-clock').isVisible(),false);
  assert.equal(await page.locator('#main-header').isVisible(),true);
  await save({clock_format:'12h'}); await page.evaluate(()=>updateData());
  console.log('PASS 18 header/mode/automatic-phase cases and independent hidden clock');

  const original=await (await context.request.get(base+'/api/data')).json();
  const fixture=JSON.parse(JSON.stringify(original));
  await page.route('**/api/data',route=>route.fulfill({json:fixture}));
  for (const [league,labels,values] of [
   ['football/nfl',['Q1','Q2','Q3','Q4','OT'],[7,7,3,3,6]],
   ['basketball/nba',['Q1','Q2','Q3','Q4','OT','2OT'],[25,24,26,25,10,9]],
   ['basketball/mens-college-basketball',['H1','H2','OT'],[30,35,8]],
   ['baseball/mlb',Array.from({length:12},(_,i)=>String(i+1)),[0,0,0,1,0,0,0,0,0,0,0,1]]]) {
   const card=JSON.parse(JSON.stringify(original.teams[0]));
   card.league_path=league;card.league_label=league==='baseball/mlb'?'MLB':'TEST';card.home_name='HOU';card.away_name='AWAY';
   card.home_rank=null;card.away_rank=null;card.home_record=league==='baseball/mlb'?'101-61':'15-10';card.away_record='12-13';
   const homeTotal=values.reduce((total,value)=>total+value,0),awayTotal=homeTotal-(league==='baseball/mlb'?1:5);
   card.game_state='final';card.is_pre=false;card.color_state='final';card.status='Final';card.home_score=String(homeTotal);card.away_score=String(awayTotal);
   card.period_scores={labels,home:values,away:values.map((value,index)=>index===values.length-1?null:value),
    totals:{home:{score:String(homeTotal),hits:league==='baseball/mlb'?11:null,errors:league==='baseball/mlb'?0:null},away:{score:String(awayTotal),hits:null,errors:null}}};
   fixture.teams=[card];fixture.specials=[];fixture.show_logo_slide=false;
   await page.evaluate(()=>updateData());
   for (const [width,height] of [[360,800],[390,844],[844,390],[1080,1920],[1920,1080],[2560,1080]]) {
    await page.setViewportSize({width,height});
    const fits=await page.evaluate(()=>{
     const card=document.querySelector('.slide.active .card').getBoundingClientRect();
     return [...document.querySelectorAll('.slide.active .team-logo-lockup,.slide.active .team-logo,.slide.active .team-abbr,.slide.active .team-record,.slide.active .score-display,.slide.active .period-breakdown')].every(el=>{
      const rect=el.getBoundingClientRect();return rect.left>=card.left-1&&rect.right<=card.right+1&&rect.top>=card.top-1&&rect.bottom<=card.bottom+1;
     }) && document.documentElement.scrollWidth<=innerWidth+1;
    });
    assert.ok(fits,`${league} details overflow ${width}x${height}`);
   }
   if (league==='baseball/mlb') {
    assert.equal(await page.locator('.period-table .period-hits').count(),3);
    assert.ok((await page.locator('.team-record').allTextContents()).includes('101-61'));
    assert.deepEqual(await page.locator('tbody .period-errors').allTextContents(),['—','0']);
    await page.setViewportSize({width:1920,height:1080});
    await page.screenshot({path:'/tmp/scoreboard-update-mlb.png'});
   }
  }
  await page.unroute('**/api/data'); await page.evaluate(()=>updateData());
  for (const [width,height,name] of [[390,844,'phone'],[1920,1080,'landscape'],[1080,1920,'portrait']]) {
   await page.setViewportSize({width,height});await page.screenshot({path:`/tmp/scoreboard-update-${name}.png`});
  }
  console.log('PASS football, NBA, NCAA halves and MLB 12-inning tables at six sizes');
  assert.deepEqual(errors,[]); console.log('PASS zero uncaught JavaScript errors');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
