# 在 PowerShell 中后台运行：  start-process powershell -ArgumentList "-File run_bot.ps1"
# 想停掉就关掉那个 PowerShell 窗口

$BotDir = "d:\Claude\TGbot-1"

while ($true) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 启动 Bot ..."
    Set-Location $BotDir
    python main.py 2>> "$BotDir\error.log"

    $exitCode = $LASTEXITCODE
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Bot 已停止 (exit=$exitCode)，3 秒后重启" -ForegroundColor Yellow
    Start-Sleep -Seconds 3
}
