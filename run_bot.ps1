# 双击运行或在终端执行： powershell -File run_bot.ps1
# 关掉窗口 = 停止 bot
# 我在 GitHub 上更新代码后，bot 重启时自动拉取最新版

$BotDir = "d:\Claude\TGbot-1"

while ($true) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 启动 Bot ..."
    Set-Location $BotDir
    # 从 GitHub 拉取最新代码（没有新提交则静默跳过）
    git pull 2>&1 | Out-Null
    python main.py 2>> "$BotDir\error.log"

    $exitCode = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Bot 已停止 (exit=$exitCode)，3 秒后重启" -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}
