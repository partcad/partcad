#!/usr/bin/env bash

set -euxo pipefail

poetry --no-ansi --no-plugins install
poetry --no-ansi --no-plugins run pytest --verbose
