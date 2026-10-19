'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const display = require('../static/js/display.js');

function game(league, labels, away, home, extra = {}) {
    return {
        league_path: league, away_name: 'TEN', home_name: 'IND',
        period_scores: {labels, away, home, totals: {away: {score: 26}, home: {score: 20}}, ...extra},
    };
}

test('header visibility validates preferences and preserves the automatic default', () => {
    for (const value of ['always', 'hidden', 'auto']) assert.equal(display.normalizeHeaderVisibility(value), value);
    for (const value of [undefined, null, '', 'show', '<script>']) assert.equal(display.normalizeHeaderVisibility(value), 'auto');
});

test('explicit header preferences override automatic timing in every display mode', () => {
    for (const mode of ['scoreboard', 'hybrid', 'ticker']) {
        for (const phase of [true, false]) {
            assert.deepEqual(display.headerState('always', phase, mode), {visible: true, collapsed: false});
            assert.deepEqual(display.headerState('hidden', phase, mode), {visible: false, collapsed: true});
        }
    }
});

test('automatic header preserves the five-minute fade phase and fullscreen ticker', () => {
    for (const mode of ['scoreboard', 'hybrid']) {
        assert.deepEqual(display.headerState('auto', true, mode), {visible: true, collapsed: false});
        assert.deepEqual(display.headerState('auto', false, mode), {visible: false, collapsed: false});
    }
    assert.deepEqual(display.headerState('auto', true, 'ticker'), {visible: false, collapsed: true});
});

test('football periods render supplied quarters, overtime and total without inventing missing zeros', () => {
    const markup = display.renderPeriodTable(game('football/nfl', ['Q1', 'Q2', 'Q3', 'Q4', 'OT'], [0, 0, 6, 20, null], [0, 13, 0, 7]));
    for (const label of ['Q1', 'Q2', 'Q3', 'Q4', 'OT']) assert.ok(markup.includes(`>${label}</th>`));
    assert.ok(markup.includes('<td>—</td>'));
    assert.ok(markup.includes('class="period-total">26</td>'));
    assert.ok(!markup.includes('period-hits'));
});

test('college basketball halves and NBA quarters use source labels', () => {
    const college = display.renderPeriodTable(game('basketball/mens-college-basketball', ['H1', 'H2', 'OT', 'OT2'], [30, 33, 8, 4], [32, 31, 8, 6]));
    assert.ok(college.includes('>H1</th>') && college.includes('>OT2</th>'));
    assert.ok(!college.includes('>Q1</th>'));
    const nba = display.renderPeriodTable(game('basketball/nba', ['Q1', 'Q2', 'Q3', 'Q4'], [30, 33, null, null], [32, 31, null, null]));
    assert.ok(nba.includes('>Q4</th>'));
});

test('MLB extra innings preserve X, runs, hits and available errors', () => {
    const markup = display.renderPeriodTable(game('baseball/mlb', Array.from({length: 12}, (_, index) => String(index + 1)), [0, 1], [0, 0, 1, null, null, null, null, null, null, null, null, 'X'], {
        totals: {away: {score: 1, hits: 4, errors: null}, home: {score: 2, hits: 6, errors: 0}},
    }));
    assert.ok(markup.includes('>12</th>') && markup.includes('<td>X</td>'));
    assert.ok(markup.includes('class="period-total">R</th>'));
    assert.ok(markup.includes('class="period-hits">H</th>'));
    assert.ok(markup.includes('class="period-errors">0</td>'));
    assert.ok(markup.includes('class="period-errors">—</td>'));
});

test('MLB omits entirely unavailable hit and error columns', () => {
    const markup = display.renderPeriodTable(game('baseball/mlb', ['1'], [0], [null]));
    assert.ok(!markup.includes('period-hits') && !markup.includes('period-errors'));
});

test('missing period data does not create a blank breakdown', () => {
    for (const value of [undefined, null, {}, {period_scores: {}}, {period_scores: {labels: []}}, {period_scores: {labels: 'Q1'}}]) {
        assert.equal(display.renderPeriodTable(value), '');
    }
});

test('period markup escapes source labels and team names and rejects malformed scores', () => {
    const value = game('football/nfl', ['<img src=x>'], ['<script>'], [false]);
    value.away_name = '<svg onload=alert(1)>';
    const markup = display.renderPeriodTable(value);
    assert.ok(markup.includes('&lt;img src=x&gt;') && markup.includes('&lt;svg onload=alert(1)&gt;'));
    assert.ok(!markup.includes('<script>') && !markup.includes('<svg '));
    assert.equal((markup.match(/<td>—<\/td>/g) || []).length, 2);
});
