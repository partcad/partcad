# Install OpenSCAD
curl -o openscad.zip https://files.openscad.org/OpenSCAD-2021.01-x86-64.zip
curl -o openscad.zip.sha256 https://files.openscad.org/OpenSCAD-2021.01-x86-64.zip.sha256
# certutil -hashfile openscad.zip SHA256 > computed.sha256
sha256sum openscad.zip | awk '{ print $1 }' > computed.sha256
if ((Get-Content openscad.zip.sha256 | awk '{ print $1 }') -ne (Get-Content computed.sha256)) {
  Write-Error "SHA256 checksum verification failed"
  exit 1
}
Expand-Archive -Force openscad.zip
Add-Content $env:GITHUB_PATH $env:GITHUB_WORKSPACE\openscad\openscad-2021.01
