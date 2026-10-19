'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const widgets = require('../static/js/live-widgets.js');

function football(overrides = {}) {
    return {
        league_path: 'football/college-football', game_state: 'live',
        football_tracker: {
            possession: 'away', team: 'TA&M', position: 66, direction: 'right',
            label: '3rd & 7 at LSU 34', quarter: 'Q3', clock: '7:52',
            red_zone: false, goal_to_go: false, ...overrides,
        },
    };
}
function baseball(overrides = {}) {
    return {
        league_path: 'baseball/mlb', game_state: 'live', away_name: 'HOU', home_name: 'NYY',
        baseball_tracker: {bases: {first: true, second: false, third: true}, inning: 6, half: 'top', outs: 1, away_score: '4', home_score: '3', ...overrides},
    };
}

test('CFB field displays possession, exact situation and normalized ball position', () => {
    const markup = widgets.render(football());
    assert.ok(markup.includes('football-tracker'));
    assert.ok(markup.includes('TA&amp;M'));
    assert.ok(markup.includes('3rd &amp; 7 at LSU 34'));
    assert.ok(markup.includes('Q3 &middot; 7:52'));
    assert.ok(markup.includes('cx="650.4"'));
    assert.ok(markup.includes('Offense moves right.'));
    assert.equal((markup.match(/field-ball"/g) || []).length, 1);
});

test('NFL and overtime share the same tracker without confusing halftime', () => {
    const value = football({quarter: '2OT'});
    value.league_path = 'football/nfl';
    value.game_state = 'overtime';
    assert.ok(widgets.render(value).includes('2OT'));
    value.game_state = 'halftime';
    assert.equal(widgets.render(value), '');
});

test('trackers are hidden for scheduled, final, postponed, canceled, stale and unknown state', () => {
    for (const state of ['scheduled', 'halftime', 'final', 'postponed', 'canceled', 'unknown', undefined, null, 'LIVE']) {
        for (const value of [football(), baseball()]) {
            value.game_state = state;
            assert.equal(widgets.render(value), '', String(state));
        }
    }
});

test('unrelated sports cannot accidentally display football or baseball trackers', () => {
    for (const league of ['basketball/nba', 'basketball/mens-college-basketball', 'baseball/college-baseball', '', undefined]) {
        const value = {...football(), ...baseball(), league_path: league};
        assert.equal(widgets.render(value), '');
    }
    for (const value of [null, undefined, false, 4, 'live', {}, []]) assert.equal(widgets.render(value), '');
});

test('missing required football facts hide only the tracker', () => {
    for (const key of Object.keys(football().football_tracker)) {
        const value = football();
        delete value.football_tracker[key];
        assert.equal(widgets.render(value), '', key);
    }
    const value = football();
    value.football_tracker = null;
    assert.equal(widgets.render(value), '');
});

test('malformed possession, field coordinates, flags and game clock are rejected', () => {
    for (const overrides of [
        {possession: 'LSU'}, {possession: 1}, {team: ''}, {team: ' '.repeat(3)}, {team: 7},
        {position: '66'}, {position: NaN}, {position: Infinity}, {position: -1}, {position: 101},
        {direction: 'left'}, {label: ''}, {label: '<'.repeat(161)},
        {quarter: 'Q0'}, {quarter: 'Q5'}, {quarter: '<script>'}, {quarter: 3},
        {clock: '7:99'}, {clock: ''}, {clock: 472}, {red_zone: 1}, {goal_to_go: 'false'},
    ]) assert.equal(widgets.render(football(overrides)), '', JSON.stringify(overrides));
});

test('own and opponent goal-line positions remain inside the same 100-yard field', () => {
    assert.ok(widgets.render(football({position: 0})).includes('cx="30"'));
    assert.ok(widgets.render(football({position: 100})).includes('cx="970"'));
    assert.ok(widgets.render(football({position: 50})).includes('cx="500"'));
});

test('red zone and goal-to-go have readable labels in addition to color', () => {
    const redZone = widgets.render(football({red_zone: true, position: 85}));
    assert.ok(redZone.includes('in-red-zone') && redZone.includes('RED ZONE'));
    const goal = widgets.render(football({red_zone: true, goal_to_go: true, label: '1st & Goal at LSU 4'}));
    assert.ok(goal.includes('GOAL TO GO') && goal.includes('1st &amp; Goal'));
    assert.ok(!widgets.render(football()).includes('football-zone-label'));
});

test('football source strings are escaped once in text and accessibility attributes', () => {
    const markup = widgets.render(football({team: '<img src=x onerror="bad"> &', label: '3rd & 7 <script>bad</script>'}));
    assert.ok(!markup.includes('<img') && !markup.includes('<script>'));
    assert.ok(markup.includes('&lt;img src=x onerror=&quot;bad&quot;&gt; &amp;'));
    assert.ok(!markup.includes('&amp;amp;'));
});

test('MLB displays supplied bases, inning half, outs and current totals', () => {
    const markup = widgets.render(baseball());
    assert.ok(markup.includes('baseball-tracker'));
    assert.ok(markup.includes('Top 6 &middot; 1 out'));
    assert.ok(markup.includes('1st / 3rd occupied'));
    assert.equal((markup.match(/diamond-base occupied/g) || []).length, 2);
    assert.ok(markup.includes('HOU <b>4</b>'));
    assert.ok(markup.includes('NYY <b>3</b>'));
    assert.ok(markup.includes('Occupied bases: first, third.'));
});

test('MLB supports extra innings, zero outs, empty bases and two outs', () => {
    const markup = widgets.render(baseball({inning: 13, half: 'bottom', outs: 0, bases: {first: false, second: false, third: false}}));
    assert.ok(markup.includes('Bottom 13 &middot; 0 outs'));
    assert.ok(markup.includes('Bases empty'));
    assert.equal((markup.match(/diamond-base occupied/g) || []).length, 0);
    assert.ok(widgets.render(baseball({outs: 2})).includes('2 outs'));
});

test('MLB unknown bases, half, inning or outs never become guessed empty bases', () => {
    for (const overrides of [
        {bases: null}, {bases: {}}, {bases: {first: true, second: false}},
        {bases: {first: 1, second: false, third: false}}, {inning: 0}, {inning: 100},
        {inning: 1.5}, {inning: '1'}, {half: 'middle'}, {half: null},
        {outs: 3}, {outs: -1}, {outs: '0'}, {outs: null},
    ]) assert.equal(widgets.render(baseball(overrides)), '', JSON.stringify(overrides));
});

test('missing or invalid MLB scores hide the widget instead of inventing current scores', () => {
    for (const unavailable of [null, undefined, '', false, 0, '<img src=x>', '-1', '3.5', '1000']) {
        assert.equal(widgets.render(baseball({home_score: unavailable})), '');
        assert.equal(widgets.render(baseball({away_score: unavailable})), '');
    }
    const markup = widgets.render(baseball({home_score: '0', away_score: '0'}));
    assert.ok(markup.includes('HOU <b>0</b>') && markup.includes('NYY <b>0</b>'));
});

test('MLB source team text cannot inject markup or accessibility attributes', () => {
    const value = baseball();
    value.away_name = '<img src=x>" & HOU';
    const markup = widgets.render(value);
    assert.ok(markup.includes('&lt;img src=x&gt;&quot; &amp; HOU'));
    assert.ok(!markup.includes('<img') && !markup.includes('&amp;amp;'));
});

test('rendering does not mutate source games, create active content or require browser globals', () => {
    for (const value of [football(), baseball()]) {
        const before = JSON.stringify(value);
        const markup = widgets.render(value);
        assert.equal(JSON.stringify(value), before);
        assert.ok(!/<(?:script|iframe|img|animate)\b|\son[a-z]+\s*=|javascript:/i.test(markup));
    }
});

test('explicitly expired or malformed server freshness hides the widget', () => {
    for (const remaining of [0, -1, null, '90', Infinity, NaN]) {
        for (const game of [football(), baseball()]) {
            game.live_detail_ttl_seconds = remaining;
            assert.equal(widgets.render(game), '');
        }
    }
    const game = football();
    game.live_detail_ttl_seconds = 90;
    assert.ok(widgets.render(game).includes('football-tracker'));
});

test('football clock never exceeds fifteen minutes or accepts invalid second precision', () => {
    for (const value of ['15:01', '16:00', '99:59', '4:20.5', '-1:00', '4:2', '15:60']) {
        assert.equal(widgets.render(football({clock: value})), '', value);
    }
    for (const value of ['0:00', '00:00', '04:20', '14:59', '15:00']) {
        assert.ok(widgets.render(football({clock: value})).includes('football-tracker'), value);
    }
});

test('validated server freshness survives rendering for the shared display expiry timer', () => {
    const game = football();
    game.live_detail_ttl_seconds = 27;
    assert.ok(widgets.render(game).includes('data-live-ttl="27"'));
    game.live_detail_ttl_seconds = 500;
    assert.ok(widgets.render(game).includes('data-live-ttl="90"'));
    delete game.live_detail_ttl_seconds;
    assert.ok(!widgets.render(game).includes('data-live-ttl='));
});
