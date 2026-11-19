#!/bin/sh
# Elaria native launcher v4. Same bind path; no browser invocation or fallback.
LAUNCH=/home/darrel/.config/elaria-console-native-v4/native_launch.py
SHA=1f575357774f3eade4fdf7cdc69ee36f2f3998ff94c61f77ab84f28bcbf56bb8
if [ "$(/usr/bin/sha256sum "$LAUNCH" 2>/dev/null)" != "$SHA  $LAUNCH" ]; then
  printf '%s\n' 'STOP: native launcher checksum mismatch; no fallback.' >&2
  exit 2
fi
exec /usr/bin/python3 -IB "$LAUNCH"
