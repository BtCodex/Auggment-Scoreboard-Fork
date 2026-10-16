# Physical Raspberry Pi acceptance checklist

Use a cloned/spare card. The original installation must remain available for rollback.
These checks have not been executed on your Pi.

- [ ] Confirm Pi 4, 2GB RAM, Pi OS version, 32/64-bit userland, Python/Chromium,
      actual service user/home, X11 versus Wayland, storage and power supply.
- [ ] Confirm backup restores favorites, enabled leagues, all uploads (including
      the real dark-green College GameDay logo), colors, slides and credentials.
- [ ] Cold boot online. Backend, applicable kiosk and display-manager services
      start, and phone settings works. Check service status/journal, not only a PID.
- [ ] Cold boot offline. Saved scores are visibly stale, the logo/dark fallback
      stays usable, and network reconnection refreshes the display.
- [ ] Delay backend startup for more than a minute. Browser waits/retries rather
      than opening a refused-connection page. Stop/start/crash-test backend and
      browser on the test card; restart cadence remains bounded (10/15 seconds).
- [ ] Save 12-hour, 24-hour, hidden and timezone preferences; restart and reboot.
      Compare Chicago time and scheduled kickoff times. Do not change a production
      clock to simulate DST; automated tests cover exact midnight/noon/DST instants.
- [ ] Verify A&M, SEC and Top 25 ranks, Texans, Astros, Rockets, PGA and all existing
      NCAA/NFL favorites. Confirm pregame/records, halftime, overtime, final,
      postponed/canceled states, bye/no-game days and changed kickoff times.
- [ ] During a real live game, observe several provider/browser refresh cycles.
      Compare against the provider; do not expect instantaneous scoring.
- [ ] Disconnect/reconnect Wi-Fi/Ethernet during games. Old scores remain marked
      stale; API errors/backoff are visible in logs; fresh data clears warnings.
- [ ] Test the actual logo upload, replacement, hidden state and explicit removal
      on the cloned card. Do not remove the only copy of your artwork. Verify its
      checksum before/after update; no white default placeholder appears.
- [ ] Test traditional, LED and hybrid modes, smooth ticker motion, slide order,
      duplicate-favorite matchups, logo timing, transitions and phone controls.
- [ ] Check portrait, landscape and ultrawide HDMI/EDID behavior plus a real iPhone.
      A simulated viewport does not verify real touch, GPU or display hardware.
- [ ] Test local calendar feeds, all optional leagues/URL slides you actually use,
      display power scheduling and reviewed Wi-Fi helper permissions.
- [ ] Run 24–48 hours across live/idle/overnight periods. Record `free -h`, backend
      and Chromium RSS/CPU, service restart/error counts, SD writes, temperature,
      `vcgencmd get_throttled` and power/undervoltage evidence where available.
- [ ] Investigate sustained memory growth, swapping/OOMs, repeated restarts,
      overheating/throttling or stale caches before unattended use.
- [ ] Rehearse rollback to the original card or private archive and confirm the
      original password representation, settings and logos all work.

Independent dual-HDMI profiles are deferred. Do not count a second mirrored window
as independent-display support; see DUAL_DISPLAY_PLAN.md.
