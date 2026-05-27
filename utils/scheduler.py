"""
Apscheduler 定时引擎 — 老师广告轮播 + 自动开奖 + 数据库定时备份
"""
import json
import logging
import os
import random
import shutil
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

from config import AD_INTERVAL_HOURS, DB_PATH, MAIN_GROUP_ID

logger = logging.getLogger(__name__)

# 确保时区检测一致
os.environ.setdefault("TZ", "Asia/Shanghai")

_scheduler = AsyncIOScheduler(timezone=ZoneInfo("Asia/Shanghai"))


def init_scheduler(app, ad_interval: int = None) -> None:
    """启动定时任务"""
    interval = ad_interval if ad_interval is not None else AD_INTERVAL_HOURS
    _scheduler.add_job(
        _teacher_ad_job, "interval", hours=interval,
        args=[app], id="teacher_ad", replace_existing=True,
    )
    _scheduler.add_job(
        _lottery_draw_job, "interval", minutes=1,
        args=[app], id="lottery_draw", replace_existing=True,
    )
    _scheduler.add_job(
        _db_backup_job, "interval", hours=6,
        args=[app], id="db_backup", replace_existing=True,
    )
    _scheduler.add_job(
        _expired_verify_job, "interval", minutes=1,
        args=[app], id="expired_verify", replace_existing=True,
    )
    _scheduler.add_job(
        _guard_unmute_job, "interval", minutes=2,
        args=[app], id="guard_unmute", replace_existing=True,
    )
    _scheduler.start()
    logger.info("定时引擎已启动（广告轮播 %dh/次，自动开奖/过期验证/禁言扫描 1-2m/次，数据库备份 6h/次）", AD_INTERVAL_HOURS)


async def _expired_verify_job(app):
    from handlers.join_verify import cleanup_expired_verifications
    await cleanup_expired_verifications(context=app)


async def _guard_unmute_job(app):
    """每 2 分钟扫描被禁言用户，已加入关联群组的自动解禁"""
    import aiosqlite
    from telegram import ChatPermissions
    from config import DB_PATH, CHANNEL_ID

    async with aiosqlite.connect(DB_PATH) as db:
        # 查询所有被禁言用户
        async with db.execute(
            "SELECT DISTINCT tg_id FROM guard_muted",
        ) as cur:
            muted_users = [r[0] for r in await cur.fetchall()]

        if not muted_users:
            return

        # 获取需关注的群组列表（优先 DB，兜底 CHANNEL_ID）
        async with db.execute(
            "SELECT chat_id FROM required_channels",
        ) as cur:
            req_channels = [r[0] for r in await cur.fetchall()]
        if not req_channels and CHANNEL_ID:
            req_channels = [CHANNEL_ID]

        if not req_channels:
            return

        bot = app.bot
        for tg_id in muted_users:
            # 检查用户是否已加入任一关联群组
            joined_any = False
            for cid in req_channels:
                try:
                    member = await bot.get_chat_member(chat_id=cid, user_id=tg_id)
                    if member.status in ("member", "administrator", "creator"):
                        joined_any = True
                        break
                except Exception:
                    continue

            if not joined_any:
                continue

            # 已加入 → 解禁所有群
            async with db.execute(
                "SELECT chat_id FROM guard_muted WHERE tg_id = ?", (tg_id,),
            ) as cur:
                mute_chats = [r[0] for r in await cur.fetchall()]

            for gid in mute_chats:
                try:
                    await bot.restrict_chat_member(
                        chat_id=gid, user_id=tg_id,
                        permissions=ChatPermissions(
                            can_send_messages=True,
                            can_send_photos=True,
                            can_send_videos=True,
                            can_send_other_messages=True,
                            can_add_web_page_previews=True,
                        ),
                    )
                    async with db.execute(
                        "DELETE FROM guard_muted WHERE tg_id = ? AND chat_id = ?",
                        (tg_id, gid),
                    )
                    await db.commit()
                    logger.info("定时解禁 user=%d chat=%d（已加入关联群组）", tg_id, gid)
                except Exception as e:
                    logger.warning("定时解禁失败 user=%d chat=%d: %s", tg_id, gid, e)


async def _teacher_ad_job(app):
    """随机抽取一名主打老师，群发到所有注册群"""
    bot = app.bot
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, region, price_info, photo_file_ids, channel_msg_link, contact "
            "FROM teachers WHERE is_promoted = 1",
        ) as cur:
            teachers = await cur.fetchall()

    if not teachers:
        logger.debug("广告轮播：无主打老师，跳过")
        return

    t = random.choice(teachers)
    name, region, price, photo_json, msg_link, contact = t

    photo_ids = json.loads(photo_json) if photo_json else []
    if not photo_ids:
        logger.warning("老师 %s 无照片，跳过广告", name)
        return

    caption = (
        f"👩‍🏫 *老师推荐：{name}*\n"
        f"📍 地区：{region or '未设置'}\n"
        f"💰 {price or '面议'}"
    )

    buttons = []
    if msg_link:
        buttons.append(InlineKeyboardButton("📎 查看频道详情", url=msg_link))
    if contact:
        url = contact if contact.startswith(("http://", "https://")) else f"https://t.me/{contact.lstrip('@')}"
        buttons.append(InlineKeyboardButton("✉️ 直接联系", url=url))
    kb = InlineKeyboardMarkup([buttons]) if buttons else None

    media = [
        InputMediaPhoto(media=fid, caption=caption if i == 0 else None)
        for i, fid in enumerate(photo_ids)
    ]

    # 取所有注册群（主群 + 附属群）
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id FROM registered_chats") as cur:
            chats = [row[0] for row in await cur.fetchall()]

    if not chats:
        logger.debug("广告轮播：无注册群，跳过")
        return

    for cid in chats:
        try:
            await bot.send_media_group(chat_id=cid, media=media)
            if kb:
                await bot.send_message(cid, "点击下方按钮了解更多 👇", reply_markup=kb)
            logger.debug("广告推送成功 chat_id=%d", cid)
        except Exception as e:
            logger.warning("广告推送失败 chat_id=%d: %s", cid, e)


async def _lottery_draw_job(app):
    """每分钟轮询已到期的抽奖并开奖"""
    now = int(datetime.now().timestamp())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, prize, target_winner_id, winner_count FROM lotteries "
            "WHERE is_active = 1 AND draw_time <= ?", (now,),
        ) as cur:
            lotteries = await cur.fetchall()

    for lid, title, prize, target_id, winner_count in lotteries:
        await _exec_draw(app, lid, title, prize, target_id, winner_count)


async def _exec_draw(app, lid, title, prize, target_id, winner_count):
    """执行单个抽奖结算"""
    bot = app.bot
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tg_id, entries FROM lottery_participants WHERE lottery_id = ?", (lid,),
        ) as cur:
            rows = await cur.fetchall()

        # 按 entries 加权构建抽奖池
        participants = []
        for tg_id, entries in rows:
            participants.extend([tg_id] * entries)

        if not participants:
            await db.execute("UPDATE lotteries SET is_active = 0 WHERE id = ?", (lid,))
            await db.commit()
            logger.info("抽奖 %s 无参与者，已关闭", title)
            return

        # 暗箱结算
        winners = []
        pool = list(participants)
        if target_id and target_id in pool:
            winners.append(target_id)
            pool.remove(target_id)
        remaining = winner_count - len(winners)
        if remaining > 0 and pool:
            winners.extend(random.sample(pool, min(remaining, len(pool))))

        await db.execute("UPDATE lotteries SET is_active = 0 WHERE id = ?", (lid,))
        await db.commit()

    # 查用户名构造中奖者列表
    links = []
    for wid in winners:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT username FROM users WHERE tg_id = ?", (wid,),
            ) as cur:
                row = await cur.fetchone()
        display = row[0] if row else f"用户{wid}"
        links.append(f'<a href="tg://user?id={wid}">{display}</a>')

    # 主群开奖喜报
    text = (
        f"🎉 *开奖啦！*\n\n"
        f"抽奖：{title}\n"
        f"奖品：{prize}\n"
        f"中奖者：{', '.join(links)}\n\n"
        f"恭喜中奖者！请联系管理员领取奖品。"
    )
    # 推送到所有注册群
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id FROM registered_chats") as cur:
            chats = [row[0] for row in await cur.fetchall()]
    if not chats:
        chats = [MAIN_GROUP_ID]
    for cid in chats:
        try:
            await bot.send_message(cid, text, parse_mode="HTML")
            logger.info("抽奖 %s 开奖结果已推送 chat_id=%d", title, cid)
        except Exception as e:
            logger.error("开奖推送 chat_id=%d 失败: %s", cid, e)

    # 私聊通知中奖者
    for wid in winners:
        try:
            await bot.send_message(
                wid,
                f"🎉 恭喜中奖！\n\n抽奖：{title}\n奖品：{prize}\n\n请前往主群联系管理员领取奖品。",
            )
        except Exception as e:
            logger.warning("通知中奖者 %d 失败: %s", wid, e)


def reschedule_ad_interval(hours: int) -> None:
    """动态修改老师轮播间隔"""
    _scheduler.reschedule_job("teacher_ad", trigger="interval", hours=hours)
    logger.info("广告轮播间隔已更新为 %d 小时", hours)


async def _db_backup_job(app):
    """每 6 小时自动备份数据库并发送到管理员 TG"""
    db_path = DB_PATH
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    name = f"bot_database_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(backup_dir, name)

    try:
        shutil.copy2(db_path, backup_path)
    except Exception as e:
        logger.error("数据库备份失败: %s", e)
        return

    # 删除 14 天前的旧备份
    cutoff = datetime.now().timestamp() - 14 * 86400
    for f in os.listdir(backup_dir):
        fp = os.path.join(backup_dir, f)
        if os.path.isfile(fp) and f.endswith(".db") and os.path.getmtime(fp) < cutoff:
            os.remove(fp)

    # 距上次 TG 发送不足 6 小时则跳过，防止频繁重启导致刷屏
    marker = os.path.join(backup_dir, ".last_backup_sent")
    now = datetime.now().timestamp()
    if os.path.exists(marker):
        try:
            last_sent = float(open(marker).read().strip())
            if now - last_sent < 6 * 3600:
                logger.info("距上次 TG 发送不足 6 小时，跳过云端备份")
                return
        except Exception:
            pass

    # 发送到管理员 TG
    send_script = os.path.join(os.path.dirname(db_path), "send_backup.py")
    try:
        subprocess.Popen([sys.executable, send_script, backup_path], creationflags=subprocess.CREATE_NO_WINDOW)
        # 记录发送时间
        with open(marker, "w") as f:
            f.write(str(now))
    except Exception as e:
        logger.error("备份发送失败: %s", e)

    logger.info("数据库已备份并发送: %s", name)
