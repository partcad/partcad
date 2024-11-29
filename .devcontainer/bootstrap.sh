#!/usr/bin/env bash

# Shell options for maximum safety:
# -e: Exit on error
# -u: Error on undefined variables
# -o pipefail: Exit on pipe failures
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspaces/partcad}"

echo "Configuring Git safe directory: ${WORKSPACE_DIR}"
if ! git config --global --add safe.directory "${WORKSPACE_DIR}"; then
    echo "Failed to configure Git safe directory. Ensure Git is installed and you have proper permissions."
    exit 1
fi

cd "${WORKSPACE_DIR}" || { echo "Failed to change directory to ${WORKSPACE_DIR}. Please verify the directory exists."; exit 1; }
if ! git config --global --add safe.directory "${WORKSPACE_DIR}"; then
    echo "Failed to configure Git safe directory"
    exit 1
fi

install_component() {
    local component="$1"
    local command="$2"

    # Input validation
    if [[ -z "${component}" || -z "${command}" ]]; then
        echo "Error: Component name and command are required"
        exit 1
    fi

    echo "Installing ${component}..."
    # shellcheck disable=SC2068
    if ! ${command[@]}; then
      echo "Failed to install ${component}"
      exit 1
    fi
}

install_component "pre-commit hooks" "pre-commit install"
# Verify pre-commit installation
if ! pre-commit --version >/dev/null 2>&1; then
    echo "Pre-commit verification failed"
    exit 1
fi
# Log installed version
echo "Pre-commit version: $(pre-commit --version)"

install_component "poetry export plugin" "poetry self add poetry-plugin-export"
# Verify poetry plugin installation
if ! poetry self show plugins | grep -q "poetry-plugin-export"; then
    echo "Poetry plugin verification failed"
    exit 1
fi
# Log installed version
echo "Poetry version: $(poetry --version)"

echo "
╔═════════════════════════════════════════════════════════╗
║ Setup Summary ($(date '+%Y-%m-%d %H:%M:%S'))            ║
╚═════════════════════════════════════════════════════════╝

- Workspace: ${WORKSPACE_DIR}
- Pre-commit: $(pre-commit --version)
- Poetry: $(poetry --version)
- Plugins: $(poetry self show plugins)

╔═════════════════════════════════════════════════════════╗
║ Dev container post-create setup completed successfully. ║
║ Humor settings: optimal (TARS approved)                 ║
╚═════════════════════════════════════════════════════════╝
"
