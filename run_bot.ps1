# 双击运行或在终端执行： powershell -File run_bot.ps1
# 关掉窗口 = 停止 bot
# 我在 GitHub 上更新代码后，bot 重启时自动拉取最新版

$BotDir = "d:\Claude\TGbot-1"
$PythonDir = "C:\Users\User002\AppData\Local\Python\pythoncore-3.14-64"
$PythonExe = "$PythonDir\python.exe"
$GitDir = "C:\Users\User002\AppData\Local\Programs\Git\bin"

# Put python/git at front of PATH to outrank WindowsApps stub
$env:Path = "$PythonDir;$GitDir;$env:Path"

# ----- 单实例保护（Named Mutex，比 lock 文件可靠）-----
$mutex = New-Object System.Threading.Mutex($false, "Global\RunBotTG")
try {
    if (-not $mutex.WaitOne(0)) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] run_bot is already running, exit" -ForegroundColor Red
        Start-Sleep -Seconds 2
        exit
    }
} catch {
    # Mutex abandoned by crashed instance -> we still own it, proceed
}

while ($true) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Starting Bot ..."
    Set-Location $BotDir

    # Kill ALL python.exe (bot instances + orphaned stubs)
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    taskkill /F /IM python.exe 2>$null
    Start-Sleep -Seconds 8

    # Pull latest code from GitHub
    git pull 2>&1 | Out-Null

    # Local DB backup (keep 14 days)
    $BackupDir = "$BotDir\backups"
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    if (Test-Path "bot_database.db") {
        $name = "bot_database_$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
        Copy-Item "bot_database.db" "$BackupDir\$name" -Force
        Get-ChildItem $BackupDir -Filter "*.db" | Where-Object {
            $_.LastWriteTime -lt (Get-Date).AddDays(-14)
        } | Remove-Item -Force
    }

    # Redirect to timestamped log (avoid file lock on crash)
    $logFile = "$BotDir\error-$(Get-Date -Format 'yyyyMMddHHmmss').log"
    & $PythonExe main.py 2> $logFile

    # Keep only latest 50 log files
    Get-ChildItem "$BotDir\error-*.log" | Sort-Object Name -Descending | Select-Object -Skip 50 | Remove-Item -Force

    $exitCode = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Bot stopped (exit=$exitCode), restart in 3s" -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}

$mutex.Dispose()
