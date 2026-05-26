"""
入群验证码处理器 — ChatJoinRequest + 私聊按钮确认
"""
import logging
import time

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ChatJoinRequestHandler, CallbackQueryHandler, filters

from config import ADMIN_IDS, DB_PATH

logger = logging.getLogger(__name__)

_VERIFY_TIMEOUT = 300
_RATE_WINDOW = 60      # 60 秒窗口
_RATE_MAX = 30          # 最多 30 个申请
_COOLDOWN = 120         # 超限后冷却 2 分钟


async def on_join_request(update: Update, context):
    """用户申请入群 → 私聊发确认按钮"""
    req = update.chat_join_request
    user = req.from_user
    chat_id = req.chat.id
    now = int(time.time())

    # 管理员自动通过
    if user.id in ADMIN_IDS:
        try:
            await req.approve()
        except Exception as e:
            logger.error("自动批准管理员失败 user=%d: %s", user.id, e)
        return

    # 开关检查
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'join_verify_enabled'") as cur:
            row = await cur.fetchone()
            if row and row[0] == "0":
                try:
                    await req.approve()
                except Exception as e:
                    logger.warning("自动通过失败（验证已关闭）user=%d: %s", user.id, e)
                return

    # 频率限制
    limiter = context.bot_data.setdefault("join_verify_limiter", {})
    group_key = str(chat_id)
    records = limiter.setdefault(group_key, [])
    records = [t for t in records if now - t < _RATE_WINDOW + _COOLDOWN]
    recent = [t for t in records if now - t < _RATE_WINDOW]
    limiter[group_key] = records

    if len(recent) >= _RATE_MAX:
        cooldown_remaining = records[-1] + _RATE_WINDOW + _COOLDOWN - now if len(records) >= _RATE_MAX else _COOLDOWN
        logger.warning("入群申请频率超限 chat=%d count=%d", chat_id, len(recent))
        try:
            await req.decline()
            await context.bot.send_message(
                user.id,
                f"当前入群申请人数过多，系统已限流，请 {_COOLDOWN // 60} 分钟后重试。",
            )
        except Exception:
            pass
        return

    records.append(now)
    limiter[group_key] = records

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO join_verify (tg_id, chat_id, code, attempts, created_at) "
            "VALUES (?, ?, '', 0, ?)",
            (user.id, chat_id, now),
        )
        await db.commit()

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 确认加入", callback_data=f"verify_join_{user.id}")],
    ])

    try:
        await context.bot.send_message(
            user.id,
            f"欢迎加入群组！\n\n点击下方按钮确认入群（{_VERIFY_TIMEOUT // 60} 分钟内有效）：",
            reply_markup=kb,
        )
        logger.info("验证消息已发送 user=%d chat=%d", user.id, chat_id)
    except Exception as e:
        logger.warning("发送验证私聊失败 user=%d: %s", user.id, e)
        await req.decline()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM join_verify WHERE tg_id = ?", (user.id,))
            await db.commit()


async def on_verify_button(update: Update, context):
    """用户点击确认按钮 → 批准入群"""
    q = update.callback_query
    user_id = int(q.data.rsplit("_", 1)[-1])

    if user_id != update.effective_user.id:
        await q.answer("这不是你的验证消息。", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id, created_at FROM join_verify WHERE tg_id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await q.answer("验证已失效，请重新申请。", show_alert=True)
        return

    chat_id, created_at = row

    if int(time.time()) - created_at > _VERIFY_TIMEOUT:
        await _decline(context, user_id, chat_id, reason="已过期")
        await q.answer("验证已过期，请重新申请。", show_alert=True)
        return

    await _approve(context, user_id, chat_id)
    await q.answer("验证通过 ✅", show_alert=False)
    try:
        await q.edit_message_text("验证通过，你已加入群组，欢迎！")
    except Exception:
        pass


async def _approve(context, user_id, chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM join_verify WHERE tg_id = ?", (user_id,))
        await db.commit()

    try:
        await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        logger.info("批准入群 user=%d chat=%d", user_id, chat_id)
    except Exception as e:
        logger.error("批准入群失败 chat=%d user=%d: %s", chat_id, user_id, e)


async def _decline(context, user_id, chat_id, reason=""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM join_verify WHERE tg_id = ?", (user_id,))
        await db.commit()

    try:
        await context.bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
    except Exception as e:
        logger.error("拒绝入群失败 chat=%d user=%d: %s", chat_id, user_id, e)

    try:
        await context.bot.send_message(user_id, f"入群申请已拒绝。{'原因：' + reason if reason else ''}")
    except Exception:
        pass


async def cleanup_expired_verifications(context=None):
    """清理过期验证（由 scheduler 每 60s 调用）"""
    now = int(time.time())
    cutoff = now - _VERIFY_TIMEOUT

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tg_id, chat_id FROM join_verify WHERE created_at < ?",
            (cutoff,),
        ) as cur:
            expired = await cur.fetchall()

    for user_id, chat_id in expired:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM join_verify WHERE tg_id = ?", (user_id,))
            await db.commit()
        try:
            await context.bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(user_id, "入群申请已过期，请重新申请。")
            logger.info("过期验证已拒绝 user=%d chat=%d", user_id, chat_id)
        except Exception as e:
            logger.warning("过期拒绝失败 user=%d: %s", user_id, e)


def register_join_verify(app, group=0) -> None:
    app.add_handler(ChatJoinRequestHandler(on_join_request))

    app.add_handler(CallbackQueryHandler(
        on_verify_button, pattern=r"^verify_join_\d+$",
    ))
