"""
群组风控处理器 — 链接禁言（主群+附属群）/ 加粉校验 / 裂变流转
"""
import asyncio
import logging
import re
import time

import aiosqlite
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ChatMemberHandler, MessageHandler, filters

from config import ADMIN_IDS, CHANNEL_ID, DB_PATH
from utils.filters import main_group, slave_group

logger = logging.getLogger(__name__)

# 匹配常见链接：http/https、www.、t.me 短链
_LINK_PATTERN = re.compile(r"(https?://|www\.)[^\s]+|t\.me/[^\s]+")

# 群组缓存，每 60 秒刷新
_CHANNEL_CACHE = {"time": 0, "data": None}  # None = 未初始化


async def _get_required_channels():
    """从 DB 获取需关注的群组列表，兜底使用 config.CHANNEL_ID。
    如果全局开关关闭则返回空列表。"""
    now = int(time.time())
    if now - _CHANNEL_CACHE["time"] < 60 and _CHANNEL_CACHE["data"] is not None:
        return _CHANNEL_CACHE["data"]

    # 检查群组校验开关
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM settings WHERE key = 'guard_enabled'",
        ) as cur:
            row = await cur.fetchone()
            if not row or row[0] != "1":
                _CHANNEL_CACHE["data"] = []
                _CHANNEL_CACHE["time"] = now
                return []

        async with db.execute(
            "SELECT chat_id, title, invite_link FROM required_channels ORDER BY id",
        ) as cur:
            rows = await cur.fetchall()

    if rows:
        _CHANNEL_CACHE["data"] = [(r[0], r[1], r[2]) for r in rows]
    elif CHANNEL_ID:
        _CHANNEL_CACHE["data"] = [(CHANNEL_ID, "关联频道", "")]
    else:
        _CHANNEL_CACHE["data"] = []
    _CHANNEL_CACHE["time"] = now
    return _CHANNEL_CACHE["data"]


async def _check_channels(user_id: int, bot) -> list | None:
    """检查用户是否已加入任一必需群组。
    返回 None = 通过，空列表 = 需提示但无按钮，非空列表 = [(title, link)] 需提示"""
    channels = await _get_required_channels()
    if not channels:
        return None  # 无要求 → 通过

    failed = []       # 能确认用户不在的群组

    for chat_id, title, invite_link in channels:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ("member", "administrator", "creator"):
                return None  # 在任意一个内 → 通过
        except Exception:
            pass  # 查不到 → 用户不在此频道，继续处理

        # 用户不在此群组 → 尝试获取邀请链接
        if not invite_link:
            try:
                invite_link = await bot.export_chat_invite_link(chat_id=chat_id)
            except Exception:
                pass  # 生不成就算了
        failed.append((title, invite_link))

    return failed if failed else None

    return failed


async def _delete_later(bot, chat_id, message_id, delay=10):
    """延迟删除消息"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug("延迟删除消息 %d 失败: %s", message_id, e)


async def _check_invitation_flow(update: Update, context):
    """裂变流转：PENDING → SUCCESS + 邀请人 +50 积分"""
    user = update.effective_user
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, inviter_id FROM invitations "
            "WHERE invitee_id = ? AND status = 'PENDING'",
            (user.id,),
        ) as cur:
            invite = await cur.fetchone()
        if not invite:
            return
        inv_id, inviter_id = invite
        await db.execute("UPDATE invitations SET status = 'SUCCESS' WHERE id = ?", (inv_id,))
        await db.execute("UPDATE users SET points = points + 50 WHERE tg_id = ?", (inviter_id,))
        # 同步加当前群 group_members
        await db.execute(
            "INSERT INTO group_members (tg_id, chat_id, points, joined_at) VALUES (?, ?, 50, ?) "
            "ON CONFLICT(tg_id, chat_id) DO UPDATE SET points = points + 50",
            (inviter_id, update.effective_chat.id, int(time.time())),
        )
        await db.commit()

    try:
        await context.bot.send_message(
            inviter_id,
            f"🎉 恭喜！您邀请的好友 {user.full_name} 已进群活跃，50 积分已到账！",
        )
        logger.info("裂变发放成功 invitee=%d inviter=%d", user.id, inviter_id)
    except Exception as e:
        logger.warning("通知邀请人 %d 失败: %s", inviter_id, e)


async def _ban_link_spammer(update: Update, context):
    """检测链接 → 非管理员直接封禁"""
    msg = update.message
    user = update.effective_user
    text = (msg.text or msg.caption or "").strip()

    if user.id in ADMIN_IDS:
        return False
    if not _LINK_PATTERN.search(text):
        return False

    logger.info("链接封禁 user=%d chat=%d", user.id, msg.chat_id)

    # 删消息
    try:
        await msg.delete()
    except Exception as e:
        logger.warning("删链接消息失败: %s", e)

    # 拉黑到黑名单
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (tg_id, username, is_banned) VALUES (?, ?, 1) "
            "ON CONFLICT(tg_id) DO UPDATE SET is_banned = 1",
            (user.id, user.full_name),
        )
        await db.commit()

    # 群内封禁（Bot 需管理员权限）
    try:
        await context.bot.ban_chat_member(chat_id=msg.chat_id, user_id=user.id)
    except Exception as e:
        logger.warning("群内封禁失败 chat=%d user=%d: %s", msg.chat_id, user.id, e)

    return True


async def slave_guard_handler(update: Update, context):
    """链接封禁 → 加粉校验 → 裂变流转"""
    msg = update.message
    user = update.effective_user

    # 1. 链接检测（所有群生效）
    if await _ban_link_spammer(update, context):
        return

    # 管理员不受群组校验限制
    if user.id in ADMIN_IDS:
        return

    # 2. 需关注的群组校验（DB 列表优先，兜底 config.CHANNEL_ID）
    failed_channels = await _check_channels(user.id, context.bot)
    if failed_channels is not None:
        logger.debug("群组校验未通过 user=%d", user.id)
        try:
            await msg.delete()
        except Exception as e:
            logger.warning("删消息失败: %s", e)

        # 禁言用户
        try:
            await context.bot.restrict_chat_member(
                chat_id=msg.chat_id,
                user_id=user.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO guard_muted (tg_id, chat_id, muted_at) VALUES (?, ?, ?)",
                    (user.id, msg.chat_id, int(time.time())),
                )
                await db.commit()
            logger.info("群组校验禁言 user=%d chat=%d", user.id, msg.chat_id)
        except Exception as e:
            logger.warning("群组校验禁言失败 chat=%d user=%d: %s", msg.chat_id, user.id, e)

        warn_text = f"{user.full_name} 您已被禁言，请先加入以下群组后等待自动解禁："
        buttons = [
            [InlineKeyboardButton(f"📢 加入 {title}", url=link)]
            for title, link in failed_channels if link
        ]
        kb = InlineKeyboardMarkup(buttons) if buttons else None
        warning = await context.bot.send_message(msg.chat_id, warn_text, reply_markup=kb)
        asyncio.create_task(_delete_later(context.bot, msg.chat_id, warning.message_id, 30))
        return

    # 3. 已通过 → 检测裂变
    text = (msg.text or msg.caption or "").strip()
    if len(text) > 3:
        await _check_invitation_flow(update, context)


async def on_chat_member_update(update: Update, context):
    """监听用户加入需关注群组 → 自动解禁"""
    member = update.chat_member
    if not member:
        return

    chat_id = update.effective_chat.id
    user = member.new_chat_member.user

    # 只处理"加入"事件（status 变为 member/administrator/creator）
    if member.new_chat_member.status not in ("member", "administrator", "creator"):
        return
    if member.old_chat_member.status in ("member", "administrator", "creator"):
        return  # 状态没变化，忽略

    # 检查这个群是否在 required_channels 中
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM required_channels WHERE chat_id = ?", (chat_id,),
        ) as cur:
            if not await cur.fetchone():
                return  # 不是需关注群组，忽略

        # 查询此用户在哪些群被禁言
        async with db.execute(
            "SELECT chat_id FROM guard_muted WHERE tg_id = ?", (user.id,),
        ) as cur:
            muted_chats = [r[0] for r in await cur.fetchall()]

    if not muted_chats:
        return

    # 逐个解禁
    for gid in muted_chats:
        try:
            await context.bot.restrict_chat_member(
                chat_id=gid,
                user_id=user.id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
        except Exception as e:
            logger.warning("自动解禁失败 chat=%d user=%d: %s", gid, user.id, e)
            continue

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM guard_muted WHERE tg_id = ? AND chat_id = ?",
                (user.id, gid),
            )
            await db.commit()
        logger.info("自动解禁 user=%d chat=%d（已加入需关注群组 %d）", user.id, gid, chat_id)

        try:
            await context.bot.send_message(
                gid,
                f"{user.full_name} 已加入关联群组，禁言已解除，欢迎发言！",
            )
        except Exception:
            pass


async def delete_join_message(update: Update, context):
    try:
        await update.message.delete()
    except Exception as e:
        logger.debug("删除入群通知失败: %s", e)


def register_group_slave(app, group=0) -> None:
    """全群组 handler 注册入口（主群 + 附属群）"""
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.StatusUpdate.NEW_CHAT_MEMBERS,
        delete_join_message,
    ), group=group)

    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.TEXT & ~filters.COMMAND,
        slave_guard_handler,
    ), group=group)

    # 监听用户加入需关注群组 → 自动解禁
    app.add_handler(ChatMemberHandler(
        on_chat_member_update, chat_member_types=ChatMemberHandler.CHAT_MEMBER,
    ))
