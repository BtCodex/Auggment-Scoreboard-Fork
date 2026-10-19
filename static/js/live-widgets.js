/* Compact live state only: no timers, network requests, dependencies or guessed data. */
(function (root) {
    'use strict';

    function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        })[char]);
    }
    function text(value, maximum) {
        return typeof value === 'string' && value.trim().length > 0 && value.length <= maximum;
    }
    function footballClock(value) {
        const match = typeof value === 'string' && /^(\d{1,2}):([0-5]\d)$/.exec(value);
        return !!match && Number(match[1]) * 60 + Number(match[2]) <= 15 * 60;
    }
    function isLive(game) {
        if (!game || typeof game !== 'object' || !['live', 'overtime'].includes(game.game_state)) return false;
        if (game.live_detail_ttl_seconds !== undefined &&
            (typeof game.live_detail_ttl_seconds !== 'number' || !Number.isFinite(game.live_detail_ttl_seconds) || game.live_detail_ttl_seconds <= 0)) return false;
        return true;
    }
    function football(game) {
        const tracker = game.football_tracker;
        if (!tracker || typeof tracker !== 'object' ||
            !['home', 'away'].includes(tracker.possession) || !text(tracker.team, 160) ||
            typeof tracker.position !== 'number' || !Number.isFinite(tracker.position) || tracker.position < 0 || tracker.position > 100 ||
            tracker.direction !== 'right' || !text(tracker.label, 160) ||
            !text(tracker.quarter, 16) || !/^(?:Q[1-4]|(?:\d+)?OT\d*)$/.test(tracker.quarter) ||
            !footballClock(tracker.clock) ||
            typeof tracker.red_zone !== 'boolean' || typeof tracker.goal_to_go !== 'boolean') return '';

        const team = escapeHtml(tracker.team.trim());
        const situation = escapeHtml(tracker.label.trim());
        const quarter = escapeHtml(tracker.quarter);
        const clock = escapeHtml(tracker.clock);
        const badge = tracker.goal_to_go ? 'GOAL TO GO' : (tracker.red_zone ? 'RED ZONE' : '');
        const accessible = escapeHtml(`${tracker.team.trim()} has possession. ${tracker.label.trim()}. ${tracker.quarter}, ${tracker.clock}. Offense moves right.${badge ? ' ' + badge + '.' : ''}`);
        // Own goal line is x=30; opponent goal line is x=970. Only validated
        // finite numbers enter SVG coordinates. Source field directions are
        // normalized by the backend so offense always attacks to the right.
        const ballX = Math.round((30 + tracker.position * 9.4) * 10) / 10;
        const yardLines = Array.from({length: 9}, (_, index) => {
            const x = 124 + index * 94;
            return `<path d="M${x} 4v20"/>`;
        }).join('');
        return `<div class="live-tracker football-tracker${tracker.red_zone ? ' in-red-zone' : ''}" role="img" aria-label="${accessible}">
            <div class="football-tracker-caption" aria-hidden="true"><span class="football-possession"><svg viewBox="0 0 24 16" focusable="false"><ellipse cx="12" cy="8" rx="10" ry="6"/><path d="M7 8h10M10 5v6M14 5v6"/></svg><span>${team}</span><span class="football-direction">&#8594;</span></span><span class="football-situation">${situation}</span>${badge ? `<span class="football-zone-label">${badge}</span>` : ''}<span class="football-time">${quarter} &middot; ${clock}</span></div>
            <svg class="football-field" viewBox="0 0 1000 28" preserveAspectRatio="none" aria-hidden="true" focusable="false"><rect class="field-surface" x="1" y="1" width="998" height="26" rx="3"/><path class="field-end-zone" d="M1 1h29v26H1zM970 1h29v26h-29z"/><path class="field-red-zone" d="M782 1h188v26H782z"/><g class="field-lines">${yardLines}<path d="M30 1v26M970 1v26M1 14h998"/></g><ellipse class="field-ball" cx="${ballX}" cy="14" rx="10" ry="6"/><path class="field-ball-laces" d="M${ballX - 5} 14h10"/></svg>
        </div>`;
    }
    function score(value) {
        return typeof value === 'string' && /^\d{1,3}$/.test(value) ? value : null;
    }
    function baseball(game) {
        const tracker = game.baseball_tracker;
        const bases = tracker && tracker.bases;
        if (!tracker || typeof tracker !== 'object' || !bases || typeof bases !== 'object' ||
            !['first', 'second', 'third'].every(base => typeof bases[base] === 'boolean') ||
            !Number.isInteger(tracker.inning) || tracker.inning < 1 || tracker.inning > 99 ||
            !['top', 'bottom'].includes(tracker.half) || !Number.isInteger(tracker.outs) || tracker.outs < 0 || tracker.outs > 2) return '';

        const half = tracker.half === 'top' ? 'Top' : 'Bottom';
        const outs = `${tracker.outs} ${tracker.outs === 1 ? 'out' : 'outs'}`;
        const awayName = text(game.away_name, 160) ? game.away_name.trim() : 'Away';
        const homeName = text(game.home_name, 160) ? game.home_name.trim() : 'Home';
        const awayScore = score(tracker.away_score);
        const homeScore = score(tracker.home_score);
        if (awayScore === null || homeScore === null) return '';
        const occupied = ['first', 'second', 'third'].filter(base => bases[base]);
        const baseDescription = occupied.length ? `Occupied bases: ${occupied.join(', ')}.` : 'Bases empty.';
        const accessible = escapeHtml(`${half} of inning ${tracker.inning}. ${outs}. ${baseDescription} ${awayName} ${awayScore}, ${homeName} ${homeScore}.`);
        const base = (name, x, y) => `<path class="diamond-base${bases[name] ? ' occupied' : ''}" d="M${x} ${y - 6}l6 6-6 6-6-6z"/>`;
        return `<div class="live-tracker baseball-tracker" role="img" aria-label="${accessible}"><svg class="baseball-diamond" viewBox="0 -2 100 68" aria-hidden="true" focusable="false"><path class="diamond-path" d="M50 58L82 32 50 6 18 32z"/>${base('first', 82, 32)}${base('second', 50, 6)}${base('third', 18, 32)}<path class="diamond-home" d="M46 53h8v5l-4 4-4-4z"/></svg><div class="baseball-live-copy" aria-hidden="true"><span class="baseball-live-inning">${half} ${tracker.inning} &middot; ${outs}</span><span class="baseball-live-bases">${occupied.length ? occupied.map(name => ({first: '1st', second: '2nd', third: '3rd'})[name]).join(' / ') + ' occupied' : 'Bases empty'}</span></div><span class="baseball-mini-score" aria-hidden="true">${escapeHtml(awayName)} <b>${awayScore}</b><span class="baseball-score-separator">&ndash;</span>${escapeHtml(homeName)} <b>${homeScore}</b></span></div>`;
    }
    function render(game) {
        if (!isLive(game)) return '';
        let html = '';
        if (['football/nfl', 'football/college-football'].includes(game.league_path)) html = football(game);
        if (game.league_path === 'baseball/mlb') html = baseball(game);
        // The display owns one shared expiry timer; no per-widget timers.
        return html && typeof game.live_detail_ttl_seconds === 'number'
            ? html.replace('class="live-tracker', `data-live-ttl="${Math.min(90, game.live_detail_ttl_seconds)}" class="live-tracker`) : html;
    }
    const widgets = {render};
    if (typeof module === 'object' && module.exports) module.exports = widgets;
    else root.ScoreboardLiveWidgets = widgets;
}(typeof window === 'undefined' ? globalThis : window));
