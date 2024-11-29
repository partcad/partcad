#!/usr/bin/env bash

# Shell options for maximum safety:
# -e: Exit on error
# -u: Error on undefined variables
# -x: Print commands before execution

git config --global --add safe.directory /workspaces/partcad

cd /workspaces/partcad || { echo "Failed to change directory"; exit 1; }

echo "Installing pre-commit hooks..."
if ! pre-commit install; then
    echo "Failed to install pre-commit hooks"
    exit 1
fi

echo "Adding poetry export plugin..."
if ! poetry self add poetry-plugin-export; then
    echo "Failed to add poetry export plugin"
    exit 1
fi

echo "Post-create setup completed successfully"
