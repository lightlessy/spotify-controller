$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Spotify Snap Control.lnk"
if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath -Force
    Write-Host "Windows başlangıcından kaldırıldı." -ForegroundColor Green
} else {
    Write-Host "Başlangıç kaydı zaten yok."
}
