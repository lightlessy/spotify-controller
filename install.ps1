$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Find-Python {
    $localCandidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )

    foreach ($candidate in $localCandidates) {
        if (Test-Path $candidate) { return $candidate }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return "py" }

    return $null
}

Write-Host ""
Write-Host "Spotify Snap Control kuruluyor..." -ForegroundColor Cyan

$python = Find-Python
if (-not $python) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-Host "Python bulunamadı ve winget kullanılamıyor." -ForegroundColor Red
        Write-Host "Python 3.11+ kurup install.bat dosyasını yeniden çalıştır."
        Read-Host "Çıkmak için Enter"
        exit 1
    }

    Write-Host "Python 3.12 bulunamadı; winget ile kullanıcı hesabına kuruluyor..."
    & winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python kurulumu başarısız oldu." }
    $python = Find-Python
    if (-not $python) {
        $python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    }
}

if ($python -eq "py") {
    & py -3 -m venv .venv
} else {
    & $python -m venv .venv
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw "Sanal ortam oluşturulamadı." }

& $venvPython -m pip install --disable-pip-version-check --upgrade pip
& $venvPython -m pip install --disable-pip-version-check -r requirements.txt

Write-Host ""
& $venvPython spotify_snap.py --check
if ($LASTEXITCODE -ne 0) {
    Write-Host "Kurulum tamamlandı ancak aygıt kontrolünde sorun çıktı." -ForegroundColor Yellow
    Write-Host "Önce mikrofon izinlerini kontrol et, sonra test.bat çalıştır."
}

Write-Host ""
$answer = Read-Host "Windows açıldığında otomatik başlasın mı? (E/H)"
if ($answer -match '^[EeYy]') {
    & "$PSScriptRoot\startup-enable.ps1"
}

Write-Host ""
Write-Host "Kurulum tamamlandı." -ForegroundColor Green
Write-Host "Şimdi start-hidden.vbs dosyasına çift tıklayabilirsin."
Read-Host "Kapatmak için Enter"
