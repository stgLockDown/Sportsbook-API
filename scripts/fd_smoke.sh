#!/usr/bin/env bash
# FanDuel production smoke test.
# Mirrors dk_smoke.sh and b365_smoke.sh patterns.
#
# Usage:
#   ./scripts/fd_smoke.sh                    # default Railway URL
#   ./scripts/fd_smoke.sh https://my-host    # custom host

set -euo pipefail

BASE="${1:-https://sportsbook-api-production-296e.up.railway.app}"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FanDuel smoke against $BASE"

# FanDuel doesn't need a session-prime endpoint (no Cloudflare/WAF),
# but we still verify /health to confirm the API is up.
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health")
echo "  /health: HTTP=$HEALTH"

for sport in nfl nba mlb nhl ncaaf ncaab wnba ufc tennis golf soccer; do
    out=$(curl -s -o /tmp/fd_smoke_$sport.json -w "HTTP=%{http_code} time=%{time_total}s" \
        "$BASE/odds/$sport/fanduel" || true)
    n=$(python3 -c "
import json, sys
try:
    d = json.load(open('/tmp/fd_smoke_$sport.json'))
    evs = d.get('data', [{}])[0].get('events', []) if d.get('data') else []
    # FD soccer convention: 'Home v Away'; US sports: 'Away @ Home'.
    games = [e for e in evs if e.get('home_team') and e.get('away_team')
             and (' @ ' in (e.get('description') or '')
                  or ' v ' in (e.get('description') or ''))]
    print(f'events={len(evs)} games={len(games)}')
except Exception as e:
    print(f'parse_error={e}')
" 2>/dev/null || echo "parse_failed")
    printf "  %-7s %s %s\n" "$sport" "$out" "$n"
done
