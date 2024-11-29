#!/usr/bin/env bash

# Shell options for maximum safety:
# -e: Exit on error
# -u: Error on undefined variables
# -x: Print commands before execution
# -o pipefail: Exit on pipe failures
set -euxo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspaces/partcad}"

echo "Configuring Git safe directory..."
if ! git config --global --add safe.directory "${WORKSPACE_DIR}"; then
    echo "Failed to configure Git safe directory"
    exit 1
fi

cd /workspaces/partcad || { echo "Failed to change directory"; exit 1; }

install_component() {
    local component="$1"
    local command="$2"

    # Input validation
    if [[ -z "${component}" || -z "${command}" ]]; then
        echo "Error: Component name and command are required"
        exit 1
    fi

    echo "Installing ${component}..."
    if ! eval "$command"; then
        echo "Failed to install ${component}"
        exit 1
    fi
}

install_component "pre-commit hooks" "pre-commit install"

install_component "poetry export plugin" "poetry self add poetry-plugin-export"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Dev container post-create setup completed successfully. Humor settings: optimal"
