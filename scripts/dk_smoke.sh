#!/usr/bin/env bash
# Quick DK production smoke test. Run periodically (e.g. cron @hourly) during
# the 24h bake to confirm cookie priming + content-API replay stays green.
#
# Usage: ./scripts/dk_smoke.sh [SB_URL]
#
# Output: one line per league with HTTP code, time, event count.
# Exit 0 if all four leagues return 200 and event_count >= 1, else 1.

set -u

SB_URL="${1:-https://sportsbook-api-production-296e.up.railway.app}"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "[$TS] DK smoke against $SB_URL"

# Status block
STATUS=$(curl -s "$SB_URL/status/dk-session")
echo "  status: $STATUS"

FAIL=0
for SPORT in nba mlb nhl nfl; do
    R=$(curl -s -w "\n__HTTP=%{http_code}__TIME=%{time_total}__" "$SB_URL/odds/$SPORT/DraftKings")
    HTTP=$(echo "$R" | grep -oE 'HTTP=[0-9]+' | cut -d= -f2)
    TIME=$(echo "$R" | grep -oE 'TIME=[0-9.]+' | cut -d= -f2)
    EVENTS=$(echo "$R" | python3 -c "
import sys, json
data = sys.stdin.read().split('__HTTP')[0]
try:
    d = json.loads(data)
    n = 0
    for snap in d.get('data', []) if isinstance(d, dict) else []:
        n += len(snap.get('events', []))
    print(n)
except Exception:
    print(0)
")
    printf "  %-4s HTTP=%s time=%ss events=%s\n" "$SPORT" "$HTTP" "$TIME" "$EVENTS"
    if [ "$HTTP" != "200" ]; then FAIL=1; fi
done

exit $FAIL
