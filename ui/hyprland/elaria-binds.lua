-- Elaria Hyprland binds — LUA config syntax (Hyprland 0.55+).
-- If `assist doctor` says "legacy .conf", use elaria-binds.conf instead.
-- Push-to-talk = press starts, release stops (Step 6 of GETTING-STARTED).
--
-- The release bind carries `ignore_mods = true` (the Lua form of the
-- `bindri` flag): the stop fires on key release whichever modifiers are
-- still held. Without it the stop only fires in one release order and a
-- Win-first release leaks the mic (scene 3b, 2026-10-26, hardware).

hl.bind("SUPER + grave",       hl.dsp.exec_cmd("assist ptt start"))
hl.bind("SUPER + grave",       hl.dsp.exec_cmd("assist ptt stop --stop-source bind"), { release = true, ignore_mods = true })
hl.bind("SUPER + SHIFT + F12", hl.dsp.exec_cmd("assist halt"))   -- panic switch (§4.4)
