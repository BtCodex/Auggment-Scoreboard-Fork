/* Shared by Chromium and dependency-free Node tests. No manual hour arithmetic. */
(function (root) {
    'use strict';
    let cachedKey;
    let cachedFormatter;

    function format(date, mode, timezone) {
        if (mode === 'hidden') return '';
        const twelveHour = mode !== '24h';
        const key = `${timezone || ''}:${twelveHour}`;
        if (!cachedFormatter || cachedKey !== key) {
            const options = {
                hour: twelveHour ? 'numeric' : '2-digit',
                minute: '2-digit',
                hourCycle: twelveHour ? 'h12' : 'h23',
            };
            if (timezone) options.timeZone = timezone;
            try {
                cachedFormatter = new Intl.DateTimeFormat('en-US', options);
            } catch (error) {
                if (!(error instanceof RangeError)) throw error;
                delete options.timeZone;
                cachedFormatter = new Intl.DateTimeFormat('en-US', options);
            }
            cachedKey = key;
        }
        // Some ICU releases use a narrow nonbreaking space before AM/PM.
        return cachedFormatter.format(date).replace(/[\u00a0\u202f]/g, ' ');
    }

    const clock = {format: format};
    if (typeof module === 'object' && module.exports) module.exports = clock;
    else root.ScoreboardClock = clock;
}(typeof window === 'undefined' ? globalThis : window));
