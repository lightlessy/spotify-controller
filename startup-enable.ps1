$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Spotify Snap Control.lnk"
$target = Join-Path $PSScriptRoot "start-hidden.vbs"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:WINDIR\System32\wscript.exe"
$shortcut.Arguments = '"' + $target + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "Parmak şıklatmasıyla Spotify kontrolü"
$shortcut.Save()

Write-Host "Windows başlangıcına eklendi." -ForegroundColor Green
