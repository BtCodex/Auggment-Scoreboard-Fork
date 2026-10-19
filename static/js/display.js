/* Small pure helpers shared by the display and dependency-free Node tests. */
(function (root) {
    'use strict';
    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        })[char]);
    }
    function safeUrl(value) {
        const text = String(value || '');
        if (/^\/static\/[a-zA-Z0-9_./%?=&+-]+$/.test(text) && !text.includes('..')) return text;
        try {
            const url = new URL(text);
            return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : '';
        } catch (_) { return ''; }
    }
    // The template interpolates these objects as markup. Escape their text once,
    // retaining raw settings for textContent, time formatting and style setters.
    function renderValue(value, key) {
        if (Array.isArray(value)) return value.map(item => renderValue(item));
        if (value && typeof value === 'object') {
            return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, renderValue(item, name)]));
        }
        if (typeof value !== 'string') return value;
        if (['logo', 'away_logo', 'home_logo', 'image', 'url'].includes(key)) return escapeHtml(safeUrl(value));
        if (key === 'color') return /^#[0-9a-f]{6}$/i.test(value) ? value : '#F5A800';
        if (key === 'color_state') return ['pre', 'live', 'final'].includes(value) ? value : 'pre';
        return escapeHtml(value);
    }
    function normalizeMode(mode) {
        return ['scoreboard', 'ticker', 'hybrid'].includes(mode) ? mode : 'hybrid';
    }
    function normalizeHeaderVisibility(value) {
        return ['always', 'hidden', 'auto'].includes(value) ? value : 'auto';
    }
    function headerState(value, automaticVisible, mode) {
        const preference = normalizeHeaderVisibility(value);
        // Automatic retains the original five-minute cycle, and the ticker's
        // full-screen presentation. Explicit choices override both behaviors.
        return {
            visible: preference === 'always' || (preference === 'auto' && mode !== 'ticker' && automaticVisible),
            collapsed: preference === 'hidden' || (preference === 'auto' && mode === 'ticker'),
        };
    }
    function topBarState(showTitle, showTime, clockFormat) {
        const title = showTitle !== false;
        const time = showTime !== false && clockFormat !== 'hidden';
        return {title, time, separator: title && time, empty: !title && !time};
    }
    function periodScore(value) {
        if (typeof value === 'number') return Number.isInteger(value) && value >= 0 ? String(value) : '—';
        if (typeof value === 'string' && (/^\d+$/.test(value) || value === 'X')) return value;
        return '—';
    }
    function renderPeriodTable(game) {
        const detail = game && game.period_scores;
        if (!detail || !Array.isArray(detail.labels) || !detail.labels.length || detail.labels.length > 60) return '';
        const sides = ['away', 'home'];
        const totals = detail.totals || {};
        const baseball = game.league_path === 'baseball/mlb';
        const statAvailable = key => sides.some(side => periodScore((totals[side] || {})[key]) !== '—');
        const extras = baseball ? ['hits', 'errors'].filter(statAvailable) : [];
        const labels = detail.labels.map(label => `<th scope="col">${escapeHtml(label)}</th>`).join('');
        const extraHeaders = extras.map(key => `<th scope="col" class="period-${key}">${key === 'hits' ? 'H' : 'E'}</th>`).join('');
        const rows = sides.map(side => {
            const values = Array.isArray(detail[side]) ? detail[side] : [];
            const cells = detail.labels.map((_, index) => `<td>${periodScore(values[index])}</td>`).join('');
            const total = totals[side] || {};
            const extraCells = extras.map(key => `<td class="period-${key}">${periodScore(total[key])}</td>`).join('');
            return `<tr><th scope="row" class="period-team-name">${escapeHtml(game[side + '_name'] || side.toUpperCase())}</th>${cells}<td class="period-total">${periodScore(total.score)}</td>${extraCells}</tr>`;
        }).join('');
        return `<div class="period-breakdown"><div class="period-scroll" tabindex="0" role="region" aria-label="${baseball ? 'Inning' : 'Period'}-by-period scores"><table class="period-table"><thead><tr><th scope="col"><span class="period-accessible-label">Team</span></th>${labels}<th scope="col" class="period-total">${baseball ? 'R' : 'T'}</th>${extraHeaders}</tr></thead><tbody>${rows}</tbody></table></div></div>`;
    }
    function collegeRank(leaguePath, rank) {
        // ESPN uses 99 (and missing values) for unranked teams. Never turn
        // other league standings or malformed provider text into a CFB badge.
        return leaguePath === 'football/college-football' && Number.isInteger(rank) && rank >= 1 && rank <= 25 ? rank : null;
    }
    function dayKey(date, timezone) {
        if (!date) return '';
        // A date-only feed item is a calendar date, not UTC midnight.
        if (typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
            const [year, month, day] = date.split('-');
            return `${month}/${day}/${year}`;
        }
        if (!Number.isFinite(new Date(date).getTime())) return '';
        const options = {year: 'numeric', month: '2-digit', day: '2-digit', timeZone: timezone || 'America/Chicago'};
        let formatter;
        try { formatter = new Intl.DateTimeFormat('en-US', options); }
        catch (_) { delete options.timeZone; formatter = new Intl.DateTimeFormat('en-US', options); }
        return formatter.format(new Date(date));
    }
    function gameKey(game) {
        return `${game.league_path || ''}:${game.event_id || ''}:${game.away_name || game.away || ''}@${game.home_name || game.home || ''}`;
    }
    function duration(value, fallback, minimum, maximum) {
        const number = Number(value);
        return Number.isFinite(number) && number >= minimum ? Math.min(maximum, number) : fallback;
    }
    const display = {escapeHtml, safeUrl, renderValue, normalizeMode, normalizeHeaderVisibility, headerState, topBarState, renderPeriodTable, collegeRank, dayKey, gameKey, duration};
    if (typeof module === 'object' && module.exports) module.exports = display;
    else root.ScoreboardDisplay = display;
}(typeof window === 'undefined' ? globalThis : window));
