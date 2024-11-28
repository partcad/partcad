#!/usr/bin/env bash

set -euxo pipefail

poetry --no-ansi --no-interaction install
poetry --no-ansi --no-interaction run pytest --verbose

pre-commit run --show-diff-on-failure --color=always --all-files
