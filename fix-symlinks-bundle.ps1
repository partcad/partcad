# Run as Administrator to create correct symlinks in local repo
# Fixes src/partcad/ai_agents symlinks so PartCAD daemon can load plugin.json

Write-Host "Creating symlinks in local repo (src/partcad/ai_agents)..." -ForegroundColor Cyan

$localPath = $PSScriptRoot
$aiAgentsDir = "$localPath\src\partcad\ai_agents"
$pluginTarget = "$localPath\ai-agents\claude\.claude-plugin\plugin.json"
$skillsTarget = "$localPath\ai-agents\claude\skills"

Write-Host "Source: $aiAgentsDir"
Write-Host "plugin.json target: $pluginTarget"
Write-Host "skills target: $skillsTarget"

# Remove broken files/symlinks
Write-Host "`nCleaning up broken symlinks/files..." -ForegroundColor Yellow
Remove-Item "$aiAgentsDir\plugin.json" -Force -ErrorAction SilentlyContinue
Remove-Item "$aiAgentsDir\skills" -Recurse -Force -ErrorAction SilentlyContinue

# Create proper symlinks
Write-Host "Creating symlink: plugin.json" -ForegroundColor Yellow
New-Item -ItemType SymbolicLink -Path "$aiAgentsDir\plugin.json" -Target $pluginTarget -Force | Out-Null

Write-Host "Creating symlink: skills" -ForegroundColor Yellow
New-Item -ItemType SymbolicLink -Path "$aiAgentsDir\skills" -Target $skillsTarget -Force | Out-Null

# Verify
Write-Host "`nVerifying..." -ForegroundColor Yellow
if (Test-Path "$aiAgentsDir\plugin.json") {
  $content = Get-Content "$aiAgentsDir\plugin.json" -Raw
  try {
    $json = $content | ConvertFrom-Json
    Write-Host "[OK] plugin.json is valid JSON" -ForegroundColor Green
    Write-Host "Plugin name: $($json.name), version: $($json.version)"
  } catch {
    Write-Host "[FAIL] plugin.json is not valid JSON" -ForegroundColor Red
  }
} else {
  Write-Host "[FAIL] plugin.json not found" -ForegroundColor Red
}

if (Test-Path "$aiAgentsDir\skills") {
  Write-Host "[OK] skills directory accessible" -ForegroundColor Green
} else {
  Write-Host "[FAIL] skills directory not found" -ForegroundColor Red
}
