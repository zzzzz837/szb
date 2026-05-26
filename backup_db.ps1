$Source = "d:\Claude\TGbot-1\bot_database.db"
$BackupDir = "d:\Claude\TGbot-1\backups"
$MaxKeep = 14  # 保留最近 14 份

# 创建备份目录
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

# 备份文件名带时间戳
$Filename = "bot_database_$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
Copy-Item $Source "$BackupDir\$Filename" -Force

# 删除超过 14 天的旧备份
Get-ChildItem $BackupDir -Filter "*.db" | Where-Object {
    $_.LastWriteTime -lt (Get-Date).AddDays(-$MaxKeep)
} | Remove-Item -Force

Write-Host "[OK] 已备份: $Filename"

# 发送到管理员 TG 私聊
python "$PSScriptRoot\send_backup.py" "$BackupDir\$Filename" 2>&1 | Out-Null
