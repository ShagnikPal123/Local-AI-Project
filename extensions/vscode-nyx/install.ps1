# Installs the Nyx Ichos VS Code extension by copying this folder into VS Code's extensions folder.
# No packaging tool needed: VS Code loads unpacked extensions from there. Restart VS Code afterwards.
$ErrorActionPreference = "Stop"
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifest = Get-Content (Join-Path $source "package.json") -Raw | ConvertFrom-Json
$name = "$($manifest.publisher).$($manifest.name)-$($manifest.version)"
$targets = @("$env:USERPROFILE\.vscode\extensions")
if (Test-Path "$env:USERPROFILE\.vscode-insiders\extensions") { $targets += "$env:USERPROFILE\.vscode-insiders\extensions" }
foreach ($root in $targets) {
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $destination = Join-Path $root $name
    if (Test-Path $destination) { Remove-Item -Recurse -Force $destination }
    Copy-Item -Recurse -Path $source -Destination $destination
    Remove-Item -Force (Join-Path $destination "install.ps1")
    Write-Host "Installed to $destination"
}
Write-Host "Restart VS Code, then press Ctrl+Alt+N to chat with Nyx or Ctrl+Alt+E to edit with an instruction."
