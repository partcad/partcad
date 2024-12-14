#!/bin/bash

# Usage:
# source env.sh

eval "$(op signin)"

# Read the .env file
while IFS= read -r line; do
  # Skip comments and empty lines
  if [[ "$line" =~ ^#.* ]] || [[ -z "$line" ]]; then
    continue
  fi

  # Extract the key and the op reference
  if [[ "$line" =~ ^([^=]+)=\"op://([^/]+)/([^/]+)/([^/]+)\"$ ]]; then
    key="${BASH_REMATCH[1]}"
    vault="${BASH_REMATCH[2]}"
    item="${BASH_REMATCH[3]}"
    field="${BASH_REMATCH[4]}"

    # Fetch the secret from 1Password
    secret=$(op item get "$item" --vault "$vault" --field "$field" --reveal)

    # Export the environment variable
    export "$key"="$secret"
  fi
done < .env

# Optionally, print the exported variables for verification
# env | grep -E 'OPENROUTER_API_KEY|PYDEVD_WARN_EVALUATION_TIMEOUT|PYDEVD_UNBLOCK_THREADS_TIMEOUT'
