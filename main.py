import logging

import aiosqlite
from telegram import Update
from telegram.ext import Application, ChatMemberHandler

from config import AD_INTERVAL_HOURS, BOT_TOKEN, DB_PATH, MAIN_GROUP_ID

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(app: Application) -> None:
    from db import init_db
    await init_db()

    # 加载附属群 ID 列表
    from utils.filters import refresh_slave_groups
    await refresh_slave_groups()

    # 读取轮播间隔设置
    interval = AD_INTERVAL_HOURS
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = 'ad_interval_hours'",
            ) as cur:
                row = await cur.fetchone()
                if row:
                    interval = int(row[0])
    except Exception:
        pass

    # 启动定时引擎
    from utils.scheduler import init_scheduler
    init_scheduler(app, ad_interval=interval)

    logger.info("Bot 启动完成，数据库 & 定时引擎已初始化")


async def chat_registered(update: Update, context) -> None:
    """Bot 被拉入群时自动注册到 registered_chats"""
    member = update.my_chat_member
    if member.new_chat_member.status in ("member", "administrator"):
        chat = update.effective_chat
        chat_type = "MAIN" if chat.id == MAIN_GROUP_ID else "SLAVE"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO registered_chats (chat_id, chat_title, chat_type) "
                "VALUES (?, ?, ?)",
                (chat.id, chat.title or "", chat_type),
            )
            await db.commit()
        logger.info("新群注册 chat_id=%d title=%s type=%s", chat.id, chat.title, chat_type)
        if chat_type == "SLAVE":
            from utils.filters import refresh_slave_groups
            await refresh_slave_groups()


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ===== 各模块 handler 注册入口 =====
    from handlers.admin import get_admin_conv_handler
    app.add_handler(get_admin_conv_handler())

    from handlers.group_main import register_group_main
    register_group_main(app)

    from handlers.private import register_private
    register_private(app)

    from handlers.group_slave import register_group_slave
    register_group_slave(app, group=-1)

    from handlers.join_verify import register_join_verify
    register_join_verify(app)

    # 自动注册 Bot 加入的群
    app.add_handler(ChatMemberHandler(chat_registered, chat_member_types=ChatMemberHandler.MY_CHAT_MEMBER))

    logger.info("Bot 开始轮询...")
    app.run_polling()


if __name__ == "__main__":
    main()
