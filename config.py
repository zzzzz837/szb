import os
from dotenv import load_dotenv

load_dotenv()

# --- Bot 凭证 ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID", "0"))
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# --- 数据持久化 ---
DB_PATH = os.getenv("DB_PATH", "bot_database.db")

# --- 关联频道（老师照片推送目标） ---
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

# --- 群邀请链接（裂变引导页） ---
GROUP_INVITE_LINK = os.getenv("GROUP_INVITE_LINK", "")

# --- 积分规则 ---
POINTS_PER_MSG = 1          # 每次发言基础积分
CHAT_COOLDOWN = 10          # 发言冷却秒数
POINTS_PER_SIGN = 5         # 每日签到积分
SIGN_STREAK_BONUS = 2       # 连续签到额外倍率（连续天数 × 此值）

# --- 定时任务 ---
AD_INTERVAL_HOURS = 2       # 老师广告轮播间隔（小时）
