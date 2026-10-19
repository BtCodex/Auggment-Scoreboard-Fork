'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const display = require('../static/js/display.js');
const CFB = 'football/college-football';

test('CFB rank badges accept all provider top 25 integer ranks', () => {
    for (let rank = 1; rank <= 25; rank++) assert.equal(display.collegeRank(CFB, rank), rank);
});

test('unranked, missing and malformed college ranks do not render badges', () => {
    for (const rank of [undefined, null, 0, -1, 26, 99, 1.5, NaN, Infinity, true, '7', '', '<img src=x>']) {
        assert.equal(display.collegeRank(CFB, rank), null);
    }
});

test('NFL and other league standings never create CFB rank badges', () => {
    for (const league of ['football/nfl', 'basketball/nba', 'basketball/mens-college-basketball', '', null, undefined]) {
        assert.equal(display.collegeRank(league, 7), null);
    }
});
