#!/usr/bin/env bash
cd "$(dirname "$(readlink -f "$0")")" || exit 1
[ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ] && echo "Warning: no DISPLAY; the window needs a desktop session (or Xvfb)." >&2
if [ -n "${1:-}" ] && [ "${1#-}" = "$1" ]; then
  account="$1"; shift
  if [ -z "${GRAAL_PASSWORD:-}" ]; then read -rsp "Password for $account: " GRAAL_PASSWORD; echo; fi
  export GRAAL_PASSWORD
  exec python3 viewer.py --account "$account" "$@"
fi
exec python3 viewer.py "$@"
