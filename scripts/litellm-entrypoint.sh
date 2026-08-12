#!/bin/sh
set -eu

read_secret() {
  variable=$1
  secret_file=$2
  if [ ! -f "$secret_file" ] || [ -L "$secret_file" ]; then
    echo "Required LiteLLM secret file is unavailable" >&2
    exit 78
  fi
  secret_value=$(cat "$secret_file")
  if [ -z "$secret_value" ]; then
    echo "Required LiteLLM secret file is empty" >&2
    exit 78
  fi
  export "$variable=$secret_value"
  unset secret_value
}

read_secret OPENAI_API_KEY /run/secrets/openai_api_key
read_secret LITELLM_MASTER_KEY /run/secrets/litellm_master_key

exec /usr/bin/litellm --config /app/config.yaml --host 0.0.0.0 --port 4000
