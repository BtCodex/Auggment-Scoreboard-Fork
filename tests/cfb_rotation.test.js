'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const display = require('../static/js/display.js');
const CFB = 'football/college-football', NFL = 'football/nfl';

function slide(league, id, time, away = 'TEAM' + id, home = 'OPP' + id) {
    return {dataset: {slideKey: `team:${league}:${id}`, eventId: String(id), leaguePath: league,
        kickoffIso: time || '', teamKeys: JSON.stringify([`${league}:${away}`, `${league}:${home}`])}};
}
function games(count = 48) {
    return Array.from({length: count}, (_, index) => slide(CFB, 4000 + index,
        new Date(Date.UTC(2026, 9, 24, 16 + Math.floor(index / 6))).toISOString()));
}
function ids(slides) { return slides.map(value => value.dataset.eventId); }
function college(slides) { return slides.filter(value => value.dataset.leaguePath === CFB); }

test('ESPN identity survives team aliases, status and kickoff corrections', () => {
    const game = {league_path: CFB, event_id:'401234567', away_name:'OU', home_name:'TA&M'};
    assert.equal(display.gameKey(game), `${CFB}:401234567`);
    assert.equal(display.gameKey(game), display.gameKey({...game, away_name:'OKLA', home_name:'TAMU',
        kickoff_iso:'2026-10-25T18:00Z', game_state:'final', home_score:'42'}));
    assert.notEqual(display.gameKey(game), display.gameKey({...game, event_id:'401234568'}));
    assert.notEqual(display.gameKey(game), display.gameKey({...game, league_path:NFL}));
});

test('legacy/manual games without IDs retain a matchup fallback', () => {
    assert.equal(display.gameKey({league_path:NFL,away_name:'HOU',home_name:'DAL'}),`${NFL}:HOU@DAL`);
    assert.equal(display.gameKey({league_path:NFL,away:'HOU',home:'DAL'}),`${NFL}:HOU@DAL`);
});

test('complete coverage is the default and legacy favorite selection remains available', () => {
    for (const value of [undefined, null, '', 'all_power5', '<script>']) assert.equal(display.normalizeCfbCoverage(value),'all_power5');
    assert.equal(display.normalizeCfbCoverage('favorites'),'favorites');
});

test('scorecard filter choices default to both without forcing completed games', () => {
    for (const value of ['live', 'upcoming', 'both']) assert.equal(display.normalizeScorecardFilter(value), value);
    for (const value of [undefined, null, '', 'all', '<script>']) assert.equal(display.normalizeScorecardFilter(value), 'both');
});

test('no-matching-game explanation is escaped and never replaces populated scorecards', () => {
    const message = 'No <live> games & scores';
    assert.equal(display.scorecardEmptyMessage({teams:[],scorecard_empty_message:message}), 'No &lt;live&gt; games &amp; scores');
    assert.equal(display.scorecardEmptyMessage({teams:[{}],scorecard_empty_message:message}), '');
    for (const value of [undefined, {}, {teams:[]}, {teams:[],scorecard_empty_message:17}, {teams:[],scorecard_empty_message:'   '}]) {
        assert.equal(display.scorecardEmptyMessage(value),'');
    }
});

test('48 complete-week cards are chronological without a featured-game cap', () => {
    const all = games(), logo = {dataset:{slideKey:'logo'}};
    const result = display.orderSlides({logo:[logo],[CFB]:[...all].reverse()},[], 'all_power5');
    assert.equal(result[0],logo);
    assert.deepEqual(ids(college(result)), ids(all));
    assert.equal(college(result).length,48);
});

test('favorite playlist inserts a complete ordered CFB block once and retains other categories', () => {
    const all = games(), nfl = slide(NFL, 'nfl', '2026-10-25T18:00Z','HOU','TEN');
    const logo = {dataset:{slideKey:'logo'}}, special = {dataset:{slideKey:'special:news'}};
    all[47].dataset.teamKeys=JSON.stringify([`${CFB}:TA&M`,`${CFB}:ALA`]);
    const playlist=[{type:'team',key:`${NFL}:HOU`},{type:'team',key:`${CFB}:TA&M`},
        {type:'logo'},{type:'team',key:`${CFB}:ALA`},{type:'team',key:`${CFB}:TA&M`},
        {type:'special',key:'special:news',uid:'news'}];
    const result = display.orderSlides({[CFB]:[...all].reverse(),logo:[logo],[NFL]:[nfl],specials:[special]},playlist,'all_power5');
    assert.equal(result[0],nfl);
    assert.deepEqual(result.slice(1,49),all);
    assert.deepEqual(result.slice(49),[logo,special]);
    assert.equal(new Set(result.map(value=>value.dataset.slideKey)).size,result.length);
});

test('an entirely unlisted CFB week is never omitted by a custom playlist', () => {
    const all = games(), nfl = slide(NFL,'nfl','2026-10-25T18:00Z','HOU','TEN');
    const result=display.orderSlides({[NFL]:[nfl],[CFB]:[...all].reverse()},[{type:'team',key:`${NFL}:HOU`}],'all_power5');
    assert.equal(result[0],nfl);
    assert.deepEqual(ids(college(result)),ids(all));
});

test('duplicate event nodes and both-favorite matchups produce exactly one slide', () => {
    const all = games();
    all[0].dataset.teamKeys=JSON.stringify([`${CFB}:TEX`,`${CFB}:MISS`]);
    const duplicate=JSON.parse(JSON.stringify(all[0]));
    const result=display.orderSlides({[CFB]:[duplicate,...all,all[0]]},[
        {type:'team',key:`${CFB}:TEX`},{type:'team',key:`${CFB}:MISS`}],'all_power5');
    assert.equal(result.length,48);
    assert.deepEqual(ids(result),ids(all));
});

test('equal kickoffs use stable event IDs and actual timestamps handle offsets', () => {
    const early=slide(CFB,'3','2026-10-24T11:00:00-05:00');
    const later=slide(CFB,'1','2026-10-24T12:00:00-04:00');
    const last=slide(CFB,'2','2026-10-24T15:00:00-05:00');
    assert.deepEqual(ids(display.orderSlides({[CFB]:[last,early,later]},[],'all_power5')),['1','3','2']);
});

test('unknown kickoffs appear last and never sort by scores/rank/status', () => {
    const all=games(3), unknown=slide(CFB,'unknown','');
    for (const [index,value] of all.entries()) Object.assign(value.dataset,{status:index?'final':'live',priority:3-index,score:30-index});
    assert.deepEqual(ids(display.orderSlides({[CFB]:[unknown,...all].reverse()},[],'all_power5')),['4000','4001','4002','unknown']);
});

test('favorites mode preserves custom team ordering and appends unmatched games', () => {
    const all=games(3);
    all[2].dataset.teamKeys=JSON.stringify([`${CFB}:SMU`,`${CFB}:TEX`]);
    const result=display.orderSlides({[CFB]:all},[{type:'team',key:`${CFB}:TEX`}],'favorites');
    assert.deepEqual(ids(result),['4002','4000','4001']);
});

test('empty/malformed playlist entries cannot erase the complete week', () => {
    const all=games(3);
    assert.deepEqual(ids(display.orderSlides({[CFB]:all},[null,{},'x',{type:'team',key:null}],'all_power5')),ids(all));
    assert.deepEqual(display.orderSlides({},[],'all_power5'),[]);
});
