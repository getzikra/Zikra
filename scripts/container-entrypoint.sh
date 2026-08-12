#!/bin/sh
set -eu

read_secret() {
  variable=$1
  file_variable=$2
  eval "secret_file=\${$file_variable:-}"
  if [ -z "$secret_file" ] || [ ! -f "$secret_file" ] || [ -L "$secret_file" ]; then
    echo "Required secret file is unavailable: $file_variable" >&2
    exit 78
  fi
  secret_value=$(cat "$secret_file")
  if [ -z "$secret_value" ]; then
    echo "Required secret file is empty: $file_variable" >&2
    exit 78
  fi
  export "$variable=$secret_value"
  unset secret_value
}

read_secret DB_PASSWORD DB_PASSWORD_FILE
read_secret ZIKRA_TOKEN ZIKRA_TOKEN_FILE
read_secret OPENAI_API_KEY LITELLM_MASTER_KEY_FILE
export ZIKRA_LLM_API_KEY="$OPENAI_API_KEY"

python /app/scripts/require-migration.py
exec "$@"
