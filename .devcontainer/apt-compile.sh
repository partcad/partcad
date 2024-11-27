#!/bin/bash

# Check for apt.in file
if [[ ! -f apt.in ]]; then
  echo "Error: apt.in file not found."
  exit 1
fi

# Ensure the script is run with sudo for apt-cache and apt-get commands
if [[ $EUID -ne 0 ]]; then
  echo "Please run this script as root or using sudo."
  exit 1
fi

# Output file
OUTPUT_FILE="apt.txt"

# Clear the output file if it exists
true > "$OUTPUT_FILE"

# Read each package from apt.in and resolve dependencies
while IFS= read -r package || [[ -n "$package" ]]; do
  if [[ -z "$package" || $package == \#* ]]; then
    # Skip empty lines or comments
    continue
  fi

  # Fetch the package version
  version=$(apt-cache policy "$package" | grep 'Installed:' | awk '{print $2}')
  if [[ -z "$version" || "$version" == "(none)" ]]; then
    echo "Warning: Package $package is not available or not installed. Skipping."
    continue
  fi

  # Add the main package with its version to the output file
  echo "$package=$version" >> "$OUTPUT_FILE"

  # Resolve dependencies
  dependencies=$(apt-cache depends "$package" | grep "Depends:" | awk '{print $2}')
  for dep in $dependencies; do
    dep_version=$(apt-cache policy "$dep" | grep 'Installed:' | awk '{print $2}')
    if [[ -n "$dep_version" && "$dep_version" != "(none)" ]]; then
      echo "$dep=$dep_version" >> "$OUTPUT_FILE"
    fi
  done
done < apt.in

# Remove duplicates and sort the output file
sort -u -o "$OUTPUT_FILE" "$OUTPUT_FILE"

echo "Locked package versions have been written to $OUTPUT_FILE."
