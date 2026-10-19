-- Elaria Hyprland binds — LUA config syntax (Hyprland 0.55+).
-- If `assist doctor` says "legacy .conf", use elaria-binds.conf instead.
-- Push-to-talk = press starts, release stops (Step 6 of GETTING-STARTED).

hl.bind("SUPER + grave",       hl.dsp.exec_cmd("assist ptt start"))
hl.bind("SUPER + grave",       hl.dsp.exec_cmd("assist ptt stop"), { release = true })
hl.bind("SUPER + SHIFT + F12", hl.dsp.exec_cmd("assist halt"))   -- panic switch (§4.4)
