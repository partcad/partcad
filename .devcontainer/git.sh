#!/usr/bin/env bash

# - https://github.com/microsoft/git?tab=readme-ov-file#ubuntudebian-distributions
# - https://devblogs.microsoft.com/devops/introducing-scalar/

set -euxo pipefail

# Install needed packages
sudo apt-get install -y curl debsig-verify

# Download public key signature file
curl -s https://api.github.com/repos/microsoft/git/releases/latest \
| grep -E 'browser_download_url.*msft-git-public.asc' \
| cut -d : -f 2,3 \
| tr -d \" \
| xargs -I 'url' curl -L -o msft-git-public.asc 'url'

# De-armor public key signature file
gpg --output msft-git-public.gpg --yes --dearmor msft-git-public.asc

# Note that the fingerprint of this key is "B8F12E25441124E1", which you can
# determine by running:
gpg --show-keys msft-git-public.asc | head -n 2 | tail -n 1 | tail -c 17

# Copy de-armored public key to debsig keyring folder
sudo mkdir -pv /usr/share/debsig/keyrings/B8F12E25441124E1
sudo mv msft-git-public.gpg /usr/share/debsig/keyrings/B8F12E25441124E1/

# Create an appropriate policy file
sudo mkdir -pv /etc/debsig/policies/B8F12E25441124E1
cat > generic.pol << EOL
<?xml version="1.0"?>
<!DOCTYPE Policy SYSTEM "https://www.debian.org/debsig/1.0/policy.dtd">
<Policy xmlns="https://www.debian.org/debsig/1.0/">
  <Origin Name="Microsoft Git" id="B8F12E25441124E1" Description="Microsoft Git public key"/>
  <Selection>
    <Required Type="origin" File="msft-git-public.gpg" id="B8F12E25441124E1"/>
  </Selection>
  <Verification MinOptional="0">
    <Required Type="origin" File="msft-git-public.gpg" id="B8F12E25441124E1"/>
  </Verification>
</Policy>
EOL

sudo mv generic.pol /etc/debsig/policies/B8F12E25441124E1/generic.pol

# Download Debian package
curl -s https://api.github.com/repos/microsoft/git/releases/latest \
| grep "browser_download_url.*deb" \
| cut -d : -f 2,3 \
| tr -d \" \
| xargs -I 'url' curl -L -o msft-git.deb 'url'

# https://github.com/microsoft/git/issues/706#issuecomment-2484482162
sudo mkdir -pv /etc/gnupg/
echo "allow-weak-digest-algos" | sudo tee /etc/gnupg/gpg.conf

# Verify
debsig-verify msft-git.deb

# Install
sudo dpkg -i msft-git.deb

# https://github.com/microsoft/git/issues/709#issuecomment-2487451368
# GIT_TRACE2_PERF=1 git maintenance start
