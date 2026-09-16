#!/usr/bin/env sh
set -eu

interval=${XRAY_SECURITY_OUTBOX_INTERVAL_SECONDS:-2}
case "$interval" in
  *[!0-9]*|'') echo 'XRAY_SECURITY_OUTBOX_INTERVAL_SECONDS must be an integer' >&2; exit 2 ;;
esac

while true; do
  python /app/backend/manage.py dispatch_security_events
  sleep "$interval"
done
