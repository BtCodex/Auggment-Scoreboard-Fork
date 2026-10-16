'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const display = require('../static/js/display.js');

test('display modes preserve hybrid defaults and accept the two focused modes', () => {
    assert.equal(display.normalizeMode(undefined), 'hybrid');
    assert.equal(display.normalizeMode('bad'), 'hybrid');
    assert.equal(display.normalizeMode('scoreboard'), 'scoreboard');
    assert.equal(display.normalizeMode('ticker'), 'ticker');
});
test('display text and attribute values are escaped, including feed titles', () => {
    const value = display.renderValue({teams: [{away_name: '<img src=x onerror="alert(1)">', away_logo: 'https://example.org/a.png?x=1&y=2'}], body: "Fish & Chips' <b>"});
    assert.equal(value.teams[0].away_name, '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
    assert.equal(value.teams[0].away_logo, 'https://example.org/a.png?x=1&amp;y=2');
    assert.equal(value.body, 'Fish &amp; Chips&#39; &lt;b&gt;');
});
test('image/embed URLs allow upload paths and HTTP(S), reject executable or credential URLs', () => {
    assert.equal(display.safeUrl('/static/uploads/logo.png?v=123'), '/static/uploads/logo.png?v=123');
    assert.equal(display.safeUrl('https://a.espncdn.com/logo.png'), 'https://a.espncdn.com/logo.png');
    for (const url of ['javascript:alert(1)', 'data:image/svg+xml,<svg>', '//untrusted.example/a', '/settings', '/static/../settings', 'https://user:secret@example.org/a']) {
        assert.equal(display.safeUrl(url), '');
    }
});
test('CSS colors and game states cannot inject arbitrary attributes or styles', () => {
    assert.deepEqual(display.renderValue({color: '#00e676', color_state: 'live'}), {color: '#00e676', color_state: 'live'});
    assert.deepEqual(display.renderValue({color: 'red; background:url(//example.org)', color_state: 'live" onmouseover="x'}), {color: '#F5A800', color_state: 'pre'});
});
test('calendar matching uses configured timezone rather than browser timezone', () => {
    assert.equal(display.dayKey('2026-01-02T05:59:00Z', 'America/Chicago'), '01/01/2026');
    assert.equal(display.dayKey('2026-01-02T06:00:00Z', 'America/Chicago'), '01/02/2026');
    assert.equal(display.dayKey('2026-07-02T05:00:00Z', 'America/Chicago'), '07/02/2026');
    assert.equal(display.dayKey('2026-01-02', 'America/Chicago'), '01/02/2026');
    assert.equal(display.dayKey('bad-date', 'America/Chicago'), '');
});
test('game keys separate repeated matchups but match card and ticker representations', () => {
    const card = {league_path: 'football/nfl', event_id: '1', away_name: 'HOU', home_name: 'DAL'};
    const ticker = {league_path: 'football/nfl', event_id: '1', away: 'HOU', home: 'DAL'};
    assert.equal(display.gameKey(card), display.gameKey(ticker));
    assert.notEqual(display.gameKey(card), display.gameKey({...card, event_id: '2'}));
});
test('timings reject invalid values and clamp excessive work', () => {
    assert.equal(display.duration('bad', 30, 30, 900), 30);
    assert.equal(display.duration(1, 30, 30, 900), 30);
    assert.equal(display.duration(Infinity, 30, 30, 900), 30);
    assert.equal(display.duration(50000, 500, 0, 2000), 2000);
    assert.equal(display.duration(0, 500, 0, 2000), 0);
});
