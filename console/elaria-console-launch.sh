#!/bin/sh
# Elaria native launcher v4. Same bind path; no browser invocation or fallback.
LAUNCH=/home/darrel/.config/elaria-console-native-v4/native_launch.py
SHA=abe107748dc65b1cd6784fe093a348c7d43999273d26cbdec5413518619c2b44
if [ "$(/usr/bin/sha256sum "$LAUNCH" 2>/dev/null)" != "$SHA  $LAUNCH" ]; then
  printf '%s\n' 'STOP: native launcher checksum mismatch; no fallback.' >&2
  exit 2
fi
exec /usr/bin/python3 -IB "$LAUNCH"
