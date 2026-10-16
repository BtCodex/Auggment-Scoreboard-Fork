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
    const display = {escapeHtml, safeUrl, renderValue, normalizeMode, dayKey, gameKey, duration};
    if (typeof module === 'object' && module.exports) module.exports = display;
    else root.ScoreboardDisplay = display;
}(typeof window === 'undefined' ? globalThis : window));
