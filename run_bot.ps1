# 双击运行或在终端执行： powershell -File run_bot.ps1
# 关掉窗口 = 停止 bot
# 我在 GitHub 上更新代码后，bot 重启时自动拉取最新版

$BotDir = "d:\Claude\TGbot-1"
$LockFile = "$BotDir\run_bot.lock"

# ----- 单实例保护：发现已有 run_bot 进程则退出 -----
if (Test-Path $LockFile) {
    $oldPid = Get-Content $LockFile -Raw
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] run_bot 已在运行 (PID=$oldPid)，退出" -ForegroundColor Red
        Start-Sleep -Seconds 2
        exit
    }
}
$PID | Out-File -Encoding utf8 $LockFile

while ($true) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 启动 Bot ..."
    Set-Location $BotDir

    # 清理旧进程，避免 409 Conflict 和文件锁
    Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3

    # 从 GitHub 拉取最新代码
    git pull 2>&1 | Out-Null

    # 本地数据库备份（保留最近 14 份，不上传）
    $BackupDir = "$BotDir\backups"
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    if (Test-Path "bot_database.db") {
        $name = "bot_database_$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
        Copy-Item "bot_database.db" "$BackupDir\$name" -Force
        Get-ChildItem $BackupDir -Filter "*.db" | Where-Object {
            $_.LastWriteTime -lt (Get-Date).AddDays(-14)
        } | Remove-Item -Force
    }

    # 覆盖日志（避免多实例争抢文件锁）
    python main.py 2> "$BotDir\error.log"

    $exitCode = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Bot 已停止 (exit=$exitCode)，3 秒后重启" -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}

Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
