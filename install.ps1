$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Test-PythonCommand {
    param(
        [string]$Command,
        [string[]]$PrefixArgs = @()
    )

    try {
        $arguments = @($PrefixArgs) + @("--version")
        & $Command $arguments *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    $localCandidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )

    foreach ($candidate in $localCandidates) {
        if ((Test-Path $candidate) -and (Test-PythonCommand -Command $candidate)) {
            return [PSCustomObject]@{ Command = $candidate; PrefixArgs = @() }
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-PythonCommand -Command $py.Source -PrefixArgs @("-3"))) {
        return [PSCustomObject]@{ Command = $py.Source; PrefixArgs = @("-3") }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-PythonCommand -Command $python.Source)) {
        return [PSCustomObject]@{ Command = $python.Source; PrefixArgs = @() }
    }

    return $null
}

function Register-FeedbackProtocol {
    param(
        [string]$PythonwPath,
        [string]$HandlerPath
    )

    $protocolRoot = "HKCU:\Software\Classes\spotify-snap"
    $commandKey = Join-Path $protocolRoot "shell\open\command"

    New-Item -Path $protocolRoot -Force | Out-Null
    Set-Item -Path $protocolRoot -Value "URL:Spotify Snap Feedback Protocol"
    New-ItemProperty `
        -Path $protocolRoot `
        -Name "URL Protocol" `
        -Value "" `
        -PropertyType String `
        -Force | Out-Null

    New-Item -Path $commandKey -Force | Out-Null
    $commandValue = "`"$PythonwPath`" `"$HandlerPath`" `"%1`""
    Set-Item -Path $commandKey -Value $commandValue

    Write-Host "Bildirim feedback dugmesi kaydedildi." -ForegroundColor Green
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

    Write-Host "Python bulunamadı; Python 3.12 kullanıcı hesabına kuruluyor..."
    & winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python kurulumu başarısız oldu." }

    $python = Find-Python
    if (-not $python) {
        $knownPython = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        if ((Test-Path $knownPython) -and (Test-PythonCommand -Command $knownPython)) {
            $python = [PSCustomObject]@{ Command = $knownPython; PrefixArgs = @() }
        } else {
            throw "Python kuruldu ancak bu oturumda bulunamadı. install.bat dosyasını yeniden çalıştır."
        }
    }
}

$venvArguments = @($python.PrefixArgs) + @("-m", "venv", ".venv")
& $python.Command $venvArguments
if ($LASTEXITCODE -ne 0) { throw "Sanal ortam oluşturulamadı." }

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$venvPythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $venvPython)) { throw "Sanal ortam oluşturulamadı." }
if (-not (Test-Path $venvPythonw)) { throw "pythonw.exe bulunamadı." }

& $venvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip güncellenemedi." }

& $venvPython -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Python paketleri kurulamadı." }

$feedbackHandler = Join-Path $PSScriptRoot "feedback_handler.py"
Register-FeedbackProtocol -PythonwPath $venvPythonw -HandlerPath $feedbackHandler

Write-Host ""
& $venvPython spotify_snap.py --check
if ($LASTEXITCODE -ne 0) {
    Write-Host "Kurulum tamamlandı ancak aygıt kontrolünde sorun çıktı." -ForegroundColor Yellow
    Write-Host "Önce mikrofon izinlerini kontrol et, sonra test.bat çalıştır."
}

& $venvPython feedback_handler.py --check
if ($LASTEXITCODE -ne 0) {
    throw "Feedback sistemi kurulamadı."
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
