"""将数据库备份文件发送到管理员 Telegram 私聊"""
import os
import sys
import asyncio

from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

if not TOKEN or not ADMIN_IDS:
    print("❌ BOT_TOKEN 或 ADMIN_IDS 未配置")
    sys.exit(1)


async def main():
    file_path = sys.argv[1]
    target_id = ADMIN_IDS[0]
    async with Bot(TOKEN) as bot:
        await bot.send_document(
            chat_id=target_id,
            document=open(file_path, "rb"),
            caption=f"📦 数据库备份：{os.path.basename(file_path)}",
        )
    print(f"✅ 已发送备份到 {target_id}")


asyncio.run(main())
