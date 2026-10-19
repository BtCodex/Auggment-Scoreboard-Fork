'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const clock = require('../static/js/clock.js');

for (const [time, twelve, twentyFour] of [
    ['00:00', '12:00 AM', '00:00'],
    ['00:01', '12:01 AM', '00:01'],
    ['09:05', '9:05 AM', '09:05'],
    ['11:59', '11:59 AM', '11:59'],
    ['12:00', '12:00 PM', '12:00'],
    ['12:01', '12:01 PM', '12:01'],
    ['13:05', '1:05 PM', '13:05'],
    ['23:59', '11:59 PM', '23:59'],
]) {
    test(time + ' in both formats', () => {
        const date = new Date('2026-01-01T' + time + ':00Z');
        assert.equal(clock.format(date, '12h', 'UTC'), twelve);
        assert.equal(clock.format(date, '24h', 'UTC'), twentyFour);
        assert.equal(clock.format(date, 'hidden', 'UTC'), '');
    });
}
test('timezone conversion crosses midnight and respects daylight saving', () => {
    assert.equal(clock.format(new Date('2026-01-02T06:00:00Z'), '12h', 'America/Chicago'), '12:00 AM');
    assert.equal(clock.format(new Date('2026-01-02T18:00:00Z'), '12h', 'America/Chicago'), '12:00 PM');
    assert.equal(clock.format(new Date('2026-07-02T05:00:00Z'), '24h', 'America/Chicago'), '00:00');
    assert.equal(clock.format(new Date('2026-01-02T05:59:00Z'), '24h', 'America/Chicago'), '23:59');
});
test('missing and unknown preferences default to twelve hours', () => {
    const date = new Date('2026-01-01T12:00:00Z');
    assert.equal(clock.format(date, undefined, 'UTC'), '12:00 PM');
    assert.equal(clock.format(date, 'unknown', 'UTC'), '12:00 PM');
});
test('invalid timezone falls back to browser timezone', () => {
    const date = new Date('2026-01-01T12:00:00Z');
    assert.equal(clock.format(date, '24h', 'invalid/timezone'), clock.format(date, '24h'));
});
test('display hides clock and separator, then restores both without a reload', () => {
    const fs = require('node:fs');
    const vm = require('node:vm');
    const path = require('node:path');
    const template = fs.readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
    const start = template.indexOf('        let clockFormat =');
    const end = template.indexOf('        setInterval(updateClock, 1000);', start);
    const code = template.slice(start, end)
        .replace('{{ settings.clock_format | tojson }}', '"hidden"')
        .replace('{{ settings.timezone | tojson }}', '"UTC"')
        .replace('{{ settings.show_time_bar | default(true) | tojson }}', 'true')
        .replace('{{ settings.show_title_bar | default(true) | tojson }}', 'true');
    const elements = {'top-clock': {textContent: ''}, 'header-sep': {}, 'display-name': {}, weather: {}};
    const context = vm.createContext({ScoreboardClock: clock, ScoreboardDisplay: require('../static/js/display.js'), Date,
        document: {getElementById: id => elements[id]}});
    vm.runInContext(code + '\nupdateClock();', context);
    assert.equal(elements['top-clock'].hidden, true);
    assert.equal(elements['header-sep'].hidden, true);
    assert.equal(elements['top-clock'].textContent, '');
    vm.runInContext("clockFormat = '24h'; updateClock();", context);
    assert.equal(elements['top-clock'].hidden, false);
    assert.equal(elements['header-sep'].hidden, false);
    assert.match(elements['top-clock'].textContent, /^\d{2}:\d{2}$/);
});
test('Chicago spring daylight saving skips the nonexistent hour', () => {
    assert.equal(clock.format(new Date('2026-03-08T07:59:00Z'), '12h', 'America/Chicago'), '1:59 AM');
    assert.equal(clock.format(new Date('2026-03-08T08:00:00Z'), '12h', 'America/Chicago'), '3:00 AM');
});
test('Chicago fall daylight saving repeats the hour without changing AM/PM', () => {
    assert.equal(clock.format(new Date('2026-11-01T06:59:00Z'), '12h', 'America/Chicago'), '1:59 AM');
    assert.equal(clock.format(new Date('2026-11-01T07:00:00Z'), '12h', 'America/Chicago'), '1:00 AM');
});
test('formatter switches between timezone and hour cycle without reusing wrong formatter', () => {
    const date = new Date('2026-01-01T06:01:00Z');
    assert.equal(clock.format(date, '12h', 'America/Chicago'), '12:01 AM');
    assert.equal(clock.format(date, '24h', 'UTC'), '06:01');
    assert.equal(clock.format(date, '12h', 'America/Chicago'), '12:01 AM');
});
