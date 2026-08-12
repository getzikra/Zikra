#!/bin/sh
set -eu
umask 077

case "$0" in
  /*) script_path=$0 ;;
  *) script_path=$PWD/$0 ;;
esac
root=$(CDPATH='' cd -- "${script_path%/*}/.." && pwd -P)
references="$root/config/zikra-secrets.op"

if [ ! -f "$references" ] || [ -L "$references" ]; then
  echo "Missing reviewed 1Password reference file: $references" >&2
  exit 78
fi

exec /opt/homebrew/bin/op run \
  --account a3tai.1password.com \
  --env-file="$references" \
  -- /usr/local/bin/docker compose \
    --project-directory "$root" \
    -f "$root/docker-compose.yml" \
    "$@"
