#!/bin/bash

# Enable strict error handling
set -euo pipefail

# Ensure the SSH agent is running
if [[ -z "${SSH_AUTH_SOCK:-}" ]]; then
    echo "Error: SSH agent is not running or SSH_AUTH_SOCK is not set."
    exit 1
fi

# Get the list of keys loaded into the SSH agent
SSH_KEYS=$(ssh-add -L 2>/dev/null || true)

if [[ -z "$SSH_KEYS" ]]; then
    echo "Error: No SSH keys found in the SSH agent."
    exit 1
fi

# Count the number of keys
KEY_COUNT=$(echo "$SSH_KEYS" | wc -l)

# If there's only one key, use it automatically
if [[ "$KEY_COUNT" -eq 1 ]]; then
    SELECTED_KEY="$SSH_KEYS"
else
    # Multiple keys loaded, prompt the user to select one
    echo "Available SSH keys in agent:"
    echo "$SSH_KEYS" | nl -w 2 -s '. '

    echo
    read -rp "Enter the number of the key to use for signing commits: " KEY_CHOICE

    # Get the selected key
    SELECTED_KEY=$(echo "$SSH_KEYS" | sed -n "${KEY_CHOICE}p")

    if [[ -z "$SELECTED_KEY" ]]; then
        echo "Error: Invalid choice."
        exit 1
    fi
fi

# Extract the key fingerprint (type and fingerprint)
SELECTED_FP=$(echo "$SELECTED_KEY" | awk '{print $1 " " $2}')

if [[ -z "$SELECTED_FP" ]]; then
    echo "Error: Unable to extract fingerprint from the selected key."
    exit 1
fi

# Get the Git user email (used as identifier in the allowed signers file)
# TODO: alexanderilyin: check that it is set
USER_EMAIL=$(git config user.email)

if [[ -z "$USER_EMAIL" ]]; then
    echo "Error: Git user.email is not configured."
    exit 1
fi

# Get the absolute path to the .git directory (repo root)
GIT_DIR=$(git rev-parse --show-toplevel)

# Define the signers file location next to the .git directory
SIGNERS_FILE="$GIT_DIR/.devcontainer/signers"

# Set up the allowedSignersFile
if [[ ! -f "$SIGNERS_FILE" ]]; then
    echo "Creating allowed signers file at $SIGNERS_FILE..."
    # Add the user email and key to the allowed signers file
    echo "$USER_EMAIL $SELECTED_FP" > "$SIGNERS_FILE"
else
    echo "Using existing allowed signers file: $SIGNERS_FILE"
    # Check if the key is already in the file; if not, append it
    if ! grep -q "$USER_EMAIL" "$SIGNERS_FILE"; then
        echo "$USER_EMAIL $SELECTED_FP" >> "$SIGNERS_FILE"
    fi
fi

# Configure Git locally to use the selected key for signing commits
echo "Configuring local Git repository to use the selected SSH key for signing..."
git config user.signingkey "$SELECTED_FP"
git config commit.gpgsign true
git config gpg.format ssh
git config gpg.ssh.allowedSignersFile "$SIGNERS_FILE"

# Output success message
echo "Git commit signing is now configured for this repository with the selected SSH key."
echo "Allowed signers file: $SIGNERS_FILE"
echo "SSH key: $SELECTED_KEY"
