# 双击运行或在终端执行： powershell -File run_bot.ps1
# 关掉窗口 = 停止 bot
# 我在 GitHub 上更新代码后，bot 重启时自动拉取最新版

$BotDir = "d:\Claude\TGbot-1"

while ($true) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 启动 Bot ..."
    Set-Location $BotDir

    # 从 GitHub 拉取最新代码
    git pull 2>&1 | Out-Null

    # 自动备份数据库（保留最近 14 份）
    $BackupDir = "$BotDir\backups"
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    if (Test-Path "bot_database.db") {
        $name = "bot_database_$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
        Copy-Item "bot_database.db" "$BackupDir\$name" -Force
        Get-ChildItem $BackupDir -Filter "*.db" | Where-Object {
            $_.LastWriteTime -lt (Get-Date).AddDays(-14)
        } | Remove-Item -Force
    }

    python main.py 2>> "$BotDir\error.log"

    $exitCode = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Bot 已停止 (exit=$exitCode)，3 秒后重启" -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}
