# 双击运行或在终端执行： powershell -File run_bot.ps1
# 关掉窗口 = 停止 bot
# 我在 GitHub 上更新代码后，bot 重启时自动拉取最新版

$BotDir = "d:\Claude\TGbot-1"
$LockFile = "$BotDir\run_bot.lock"

# ----- 单实例保护 -----
if (Test-Path $LockFile) {
    $oldPid = Get-Content $LockFile -Raw
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] run_bot is already running (PID=$oldPid), exit" -ForegroundColor Red
        Start-Sleep -Seconds 2
        exit
    }
}
$PID | Out-File -Encoding utf8 $LockFile

while ($true) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Starting Bot ..."
    Set-Location $BotDir

    # Kill old processes to avoid 409 Conflict
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3

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

    # Overwrite log to avoid file lock conflicts
    python main.py 2> "$BotDir\error.log"

    $exitCode = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Bot stopped (exit=$exitCode), restart in 3s" -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}

Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
