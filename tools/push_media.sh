#!/usr/bin/env bash
# Copy the rebuilt backup to the phone: one `adb push` per media folder, all in parallel.
#
# A single `adb push` of tens of thousands of small files (photos, voice notes, stickers) runs at
# a few MB/s because every file costs a round trip; parallel pushes reached ~35 MB/s in testing.
# --sync skips files already on the phone, so the script can be run again after an interruption.
#
# Usage: push_media.sh OUTPUT_DIR
#   OUTPUT_DIR  the --output-dir of `wa-fuse pipeline` (contains msgstore.db.crypt15 and WhatsApp/Media)
# Run it after `adb shell pm clear com.whatsapp` and before opening WhatsApp.
set -euo pipefail

OUT=$(cd "$1" && pwd)
DEST=/sdcard/Android/media/com.whatsapp/WhatsApp

adb shell mkdir -p "$DEST/Media" "$DEST/Databases"
pids=()
for dir in "$OUT/WhatsApp/Media"/*/; do
  dir=${dir%/}
  adb push --sync "$dir" "$DEST/Media/" > "/tmp/push-$(basename "$dir" | tr ' ' '_').log" 2>&1 &
  pids+=($!)
done
status=0
for pid in "${pids[@]}"; do wait "$pid" || status=1; done
[ "$status" -eq 0 ] || { echo "A folder failed: see /tmp/push-*.log and run again" >&2; exit 1; }

adb push "$OUT/msgstore.db.crypt15" "$DEST/Databases/msgstore.db.crypt15"
echo "Files on the phone: $(adb shell "find '$DEST/Media' -type f | wc -l")"
echo "Files on the computer: $(find "$OUT/WhatsApp/Media" -type f | wc -l | tr -d ' ')"
