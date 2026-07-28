$processes = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq "pythonw.exe" -or $_.Name -eq "python.exe") -and
    ($_.CommandLine -like "*spotify_snap_feedback.py*" -or
     $_.CommandLine -like "*spotify_snap.py*")
}

if (-not $processes) {
    Write-Host "Spotify Snap Control zaten çalışmıyor."
    exit 0
}

foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force
}

Write-Host "Spotify Snap Control kapatıldı." -ForegroundColor Green
