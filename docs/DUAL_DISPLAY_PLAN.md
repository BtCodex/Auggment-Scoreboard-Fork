# Two independent HDMI displays: tested foundation and next step

Independent HDMI placement is deliberately deferred. Two windows of the current
root display share the saved display configuration; this candidate does not claim
they can be assigned separate settings from the UI.

The backend foundation was tested: concurrent-style POST /api/data calls selecting
college football and NFL return separate favorite-game sets without changing
settings.json. They share the same provider cache; duplicate favorites are deduped.
Requested league/date-window demand is bounded and expires after 15 minutes.
Conference fetching is still a central server setting, so independent conference
filters are not yet supported by shared-cache profiles.

A compatible next implementation should add named profiles to the existing saved
configuration, not another Python service:

1. `/display/college` selects CFB/FBS, A&M, SEC and Top 25.
2. `/display/pro` selects NFL/HOU, NBA/HOU, MLB/HOU and PGA.
3. Public display data is restricted to the profile's safe presentation/filter
   fields; credentials and global service controls remain in authenticated settings.
4. Cache keys include source/conference variants where required; fetch the union of
   active profile date windows once. Profile edits never overwrite other profiles.
5. Launch two Chromium windows with separate user-data directories and positions
   derived from actual X11 output geometry. Do not assume HDMI connector names,
   monitor order, resolution, or Wayland behavior.

Before implementing, add profile migration/concurrency/ordering tests and a browser
check with two independent contexts. On the Pi, measure two 1080p displays first,
including reconnect/EDID changes, browser crash recovery, RAM/GPU use and heat.
Two 4K displays should not be assumed practical on a 2GB Pi. A second lightweight
kiosk device using the same server remains an alternative if memory is tight.
