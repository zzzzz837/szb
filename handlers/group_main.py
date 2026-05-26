"""
主群核心交互处理器 — 签到 / 积分 / 排行榜 / 控分 / 老师触发
"""
import json
import logging
import random
import re
from datetime import datetime, timedelta

import aiosqlite
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

from config import CHAT_COOLDOWN, DB_PATH, POINTS_PER_MSG, POINTS_PER_SIGN
from utils.filters import main_group, slave_group, is_admin

logger = logging.getLogger(__name__)


# ============================== 工具函数 ==============================

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _ts() -> int:
    return int(datetime.now().timestamp())


def _display(uid: int, uname: str | None) -> str:
    """返回 @username 或带超链接的 FirstName"""
    if uname:
        return f"@{uname}"
    return f'<a href="tg://user?id={uid}">用户{uid}</a>'


# ============================== 1. 发言活跃积分 ==============================

async def active_points_handler(update: Update, context):
    """每次发言 +1 积分，带 10s 冷却 + 每日 300 上限"""
    text = update.message.text.strip()
    if len(text) <= 3:
        return

    user = update.effective_user
    tg_id = user.id
    now_ts = _ts()
    today = _today()

    # 内存级每日计数（bot 重启后重置，可接受）
    daily = context.bot_data.setdefault("chat_counts", {})
    key = f"{update.effective_chat.id}_{tg_id}_{today}"
    if daily.get(key, 0) >= 300:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT last_chat_time FROM group_members WHERE tg_id = ? AND chat_id = ?",
            (tg_id, update.effective_chat.id),
        ) as cur:
            row = await cur.fetchone()

        if row and row[0] and now_ts < row[0] + CHAT_COOLDOWN:
            return

        # 写 per-group 数据
        await db.execute(
            "INSERT INTO group_members (tg_id, chat_id, username, points, last_chat_time, joined_at, total_msgs) "
            "VALUES (?, ?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(tg_id, chat_id) DO UPDATE SET "
            "  points = points + ?,"
            "  last_chat_time = ?,"
            "  total_msgs = total_msgs + 1,"
            "  username = ?",
            (tg_id, update.effective_chat.id, user.full_name, POINTS_PER_MSG, now_ts, now_ts,
             POINTS_PER_MSG, now_ts, user.full_name),
        )
        # 同步写全局 users 表（兼容抽奖/兑换）
        await db.execute(
            "INSERT INTO users (tg_id, username, points, last_chat_time, joined_at, total_msgs) "
            "VALUES (?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(tg_id) DO UPDATE SET "
            "  points = points + ?,"
            "  last_chat_time = ?,"
            "  total_msgs = total_msgs + 1,"
            "  username = ?",
            (tg_id, user.full_name, POINTS_PER_MSG, now_ts, now_ts,
             POINTS_PER_MSG, now_ts, user.full_name),
        )
        await db.commit()

    daily[key] = daily.get(key, 0) + 1


# ============================== 2. 每日签到 ==============================

async def sign_in_handler(update: Update, context):
    """签到 + 连续签到阶梯奖励"""
    user = update.effective_user
    tg_id = user.id
    today = _today()

    async with aiosqlite.connect(DB_PATH) as db:
        # 重复签到拦截
        async with db.execute(
            "SELECT streak_days FROM attendance WHERE tg_id = ? AND log_date = ?",
            (tg_id, today),
        ) as cur:
            if await cur.fetchone():
                await update.message.reply_text("您今天已经签到过了哦！")
                return

        # 计算连续天数
        async with db.execute(
            "SELECT streak_days FROM attendance WHERE tg_id = ? AND log_date = ?",
            (tg_id, _yesterday()),
        ) as cur:
            row = await cur.fetchone()
        streak = (row[0] if row else 0) + 1

        # 积分结算
        bonus = 0
        if streak >= 30:
            bonus += random.randint(10, 30)
        if streak >= 15:
            bonus += random.randint(10, 30)
        if streak >= 7:
            bonus += 50
        if streak >= 3:
            bonus += 20

        total = POINTS_PER_SIGN + bonus

        # 写签到记录
        await db.execute(
            "INSERT INTO attendance (tg_id, log_date, streak_days) VALUES (?, ?, ?)",
            (tg_id, today, streak),
        )

        # 更新用户积分（写 group_members 和 users）
        chat_id = update.effective_chat.id

        async with db.execute(
            "SELECT points FROM group_members WHERE tg_id = ? AND chat_id = ?",
            (tg_id, chat_id),
        ) as cur:
            exist = await cur.fetchone()

        if exist is None:
            current = total
            await db.execute(
                "INSERT INTO group_members (tg_id, chat_id, username, points, joined_at) VALUES (?, ?, ?, ?, ?)",
                (tg_id, chat_id, user.full_name, current, _ts()),
            )
        else:
            current = exist[0] + total
            await db.execute(
                "UPDATE group_members SET points = points + ?, username = ? WHERE tg_id = ? AND chat_id = ?",
                (total, user.full_name, tg_id, chat_id),
            )

        # 同步写全局 users 表
        await db.execute(
            "INSERT INTO users (tg_id, username, points, joined_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(tg_id) DO UPDATE SET points = points + ?, username = ?",
            (tg_id, user.full_name, total, _ts(), total, user.full_name),
        )
        await db.commit()

    text = (
        f"✨ 签到成功！\n"
        f"📅 连续签到：{streak} 天\n"
        f"💰 本次获得：{total} 积分（基础 {POINTS_PER_SIGN}"
    )
    if bonus:
        text += f" + 奖励 {bonus}"
    text += f"）\n当前总积分：{current}"
    await update.message.reply_text(text)


# ============================== 3. 排行榜（翻页 Top 100） ==============================

_PAGE_SIZE = 10


async def _build_leaderboard_page(chat_id: int, rank_type: str, page: int, context) -> tuple:
    """构建排行榜某页内容，返回 (text, keyboard)"""
    start = (page - 1) * _PAGE_SIZE
    end = start + _PAGE_SIZE
    total = 0

    async with aiosqlite.connect(DB_PATH) as db:
        if rank_type == "today":
            daily = context.bot_data.get("chat_counts", {})
            today = _today()
            raw = {}
            for k, v in daily.items():
                parts = k.split("_", 2)
                if len(parts) == 3 and parts[2] == today and int(parts[0]) == chat_id:
                    raw[int(parts[1])] = raw.get(int(parts[1]), 0) + v
            top = sorted(raw.items(), key=lambda x: x[1], reverse=True)[:100]
            if not top:
                return "📭 今日暂无活跃数据。", None
            total = len(top)
            page_data = top[start:end]
            ids = [u for u, _ in page_data]
            where = ",".join("?" for _ in ids)
            async with db.execute(f"SELECT tg_id, username FROM users WHERE tg_id IN ({where})", ids) as cur:
                nm = {r[0]: r[1] for r in await cur.fetchall()}
            icon, title, unit = "👑", "今日群活跃", "条"
            items = [(uid, cnt, nm.get(uid)) for uid, cnt in page_data]

        elif rank_type == "active":
            async with db.execute(
                "SELECT tg_id, username, total_msgs FROM group_members WHERE chat_id = ? ORDER BY total_msgs DESC LIMIT 100",
                (chat_id,),
            ) as cur:
                rows = await cur.fetchall()
            if not rows:
                return "📭 暂无发言数据。", None
            total = len(rows)
            page_data = rows[start:end]
            icon, title, unit = "🔥", "群活跃总", "条"
            items = [(uid, msgs, uname) for uid, uname, msgs in page_data]

        elif rank_type == "points":
            async with db.execute(
                "SELECT tg_id, username, points FROM group_members WHERE chat_id = ? ORDER BY points DESC LIMIT 100",
                (chat_id,),
            ) as cur:
                rows = await cur.fetchall()
            if not rows:
                return "📭 暂无积分数据。", None
            total = len(rows)
            page_data = rows[start:end]
            icon, title, unit = "🏆", "群积分", "分"
            items = [(uid, pts, uname) for uid, uname, pts in page_data]

        elif rank_type == "invite":
            async with db.execute(
                "SELECT inviter_id, COUNT(*) AS cnt FROM invitations WHERE status = 'SUCCESS' "
                "GROUP BY inviter_id ORDER BY cnt DESC LIMIT 100",
            ) as cur:
                rows = await cur.fetchall()
            if not rows:
                return "📭 暂无邀请数据。", None
            total = len(rows)
            page_data = rows[start:end]
            ids = [r[0] for r in page_data]
            where = ",".join("?" for _ in ids)
            async with db.execute(f"SELECT tg_id, username FROM users WHERE tg_id IN ({where})", ids) as cur:
                nm = {r[0]: r[1] for r in await cur.fetchall()}
            icon, title, unit = "🎯", "邀请", "人"
            items = [(uid, cnt, nm.get(uid)) for uid, cnt in page_data]

    lines = [f"{icon} {title}排行榜（第{page}/{max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)}页）"]
    for i, (uid, val, uname) in enumerate(items, start + 1):
        lines.append(f"{i}. {_display(uid, uname)} — {val} {unit}")
    text = "\n".join(lines)

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"lb_{rank_type}_{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"lb_{rank_type}_{page + 1}"))
    kb = InlineKeyboardMarkup([nav]) if nav else None
    return text, kb


async def leaderboard_handler(update: Update, context):
    """排行榜入口 — 显示第 1 页"""
    type_map = {"今日排行": "today", "活跃排行": "active", "积分排行": "points", "邀请排行": "invite"}
    rank_type = type_map.get(update.message.text.strip())
    if not rank_type:
        return
    content, kb = await _build_leaderboard_page(update.effective_chat.id, rank_type, 1, context)
    await update.message.reply_text(content, reply_markup=kb, parse_mode="HTML")


async def leaderboard_page_callback(update: Update, context):
    """排行榜翻页"""
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")  # lb_today_2, lb_points_1
    content, kb = await _build_leaderboard_page(
        update.effective_chat.id, parts[1], int(parts[2]), context,
    )
    await q.edit_message_text(content, reply_markup=kb, parse_mode="HTML")


# ============================== 4. 邀请链接 ==============================


async def invite_handler(update: Update, context):
    """生成个人邀请链接"""
    bot_me = context.bot_data.get("bot_me")
    if not bot_me:
        bot_me = await context.bot.get_me()
        context.bot_data["bot_me"] = bot_me
    link = f"https://t.me/{bot_me.username}?start=invite_{update.effective_user.id}"
    await update.message.reply_text(
        f"🔗 你的专属邀请链接：\n{link}\n\n"
        f"分享给好友，对方通过此链接注册后你将获得邀请奖励！",
    )


# ============================== 5. 管理员控分 ==============================

async def admin_points_handler(update: Update, context):
    """加积分N / 减积分N，需回复目标用户"""
    if not update.message.reply_to_message:
        await update.message.reply_text("请回复一条消息来操作积分。")
        return

    match = re.match(r"^(加积分|减积分)\s?(\d+)$", update.message.text.strip())
    if not match:
        return

    action, raw_pts = match.group(1), int(match.group(2))
    target = update.message.reply_to_message.from_user
    points = raw_pts if action == "加积分" else -raw_pts

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT points FROM users WHERE tg_id = ?", (target.id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            new_pts = max(0, points)
            await db.execute(
                "INSERT INTO users (tg_id, username, points, joined_at) VALUES (?, ?, ?, ?)",
                (target.id, target.full_name, new_pts, _ts()),
            )
        else:
            new_pts = max(0, row[0] + points)
            await db.execute(
                "UPDATE users SET points = ?, username = ? WHERE tg_id = ?",
                (new_pts, target.full_name, target.id),
            )
        await db.commit()

    display = target.username or target.full_name
    verb = "加" if points > 0 else "减"
    await update.message.reply_text(
        f"操作成功！已为 @{display} {verb} {raw_pts} 积分（当前 {new_pts} 分）。",
    )


# ============================== 6. 管理员禁言/解禁 ==============================


async def mute_handler(update: Update, context):
    """禁言回复的用户 N 分钟"""
    if not update.message.reply_to_message:
        await update.message.reply_text("请回复一条消息来禁言用户。")
        return
    match = re.match(r"^禁言\s*(\d+)\s*$", update.message.text.strip())
    if not match:
        await update.message.reply_text("格式：禁言 5（禁言5分钟）")
        return

    minutes = int(match.group(1))
    target = update.message.reply_to_message.from_user
    until = int(datetime.now().timestamp()) + minutes * 60

    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await update.message.reply_text(f"✅ 已禁言 {target.full_name} {minutes} 分钟。")
    except Exception as e:
        await update.message.reply_text(f"❌ 禁言失败：{e}")


async def unmute_handler(update: Update, context):
    """解禁回复的用户"""
    if not update.message.reply_to_message:
        await update.message.reply_text("请回复一条消息来解禁用户。")
        return
    target = update.message.reply_to_message.from_user

    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await update.message.reply_text(f"✅ 已解禁 {target.full_name}。")
    except Exception as e:
        await update.message.reply_text(f"❌ 解禁失败：{e}")


# ============================== 7. 查积分 / 积分兑换 / 抽奖列表 ==============================


async def my_points_handler(update: Update, context):
    """查自己在当前群的积分"""
    tg_id = update.effective_user.id
    chat_id = update.effective_chat.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT points FROM group_members WHERE tg_id = ? AND chat_id = ?",
            (tg_id, chat_id),
        ) as cur:
            row = await cur.fetchone()
    pts = row[0] if row else 0
    await update.message.reply_text(f"💰 您在当前群的积分为：{pts} 分")


async def shop_handler(update: Update, context):
    """积分兑换 — 商品列表"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, description, price, stock FROM products WHERE is_active = 1 ORDER BY id",
        ) as cur:
            products = await cur.fetchall()
    if not products:
        await update.message.reply_text("暂无上架商品。")
        return
    lines = ["🛒 *积分兑换*\n"]
    for p in products:
        lines.append(f"**{p[1]}** — {p[3]} 积分（库存 {p[4]}）\n  {p[2]}")
    kb = [[InlineKeyboardButton(f"🛒 {p[1]}", callback_data=f"buy_{p[0]}")] for p in products]
    await update.message.reply_text(
        "\n".join(lines), reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown",
    )


async def lottery_list_handler(update: Update, context):
    """进行中的抽奖列表"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'lottery_enabled'") as cur:
            row = await cur.fetchone()
            if not row or row[0] != "1":
                return
        async with db.execute(
            "SELECT id, title, description, prize, cost_points, draw_time, "
            "winner_count FROM lotteries WHERE is_active = 1 ORDER BY id DESC",
        ) as cur:
            lotteries = await cur.fetchall()
    if not lotteries:
        await update.message.reply_text("暂无进行中的抽奖。")
        return
    for l in lotteries:
        lid, title, desc, prize, cost, draw_ts, wcnt = l
        draw_str = datetime.fromtimestamp(draw_ts).strftime("%Y-%m-%d %H:%M")
        text = (
            f"🎁 *{title}*\n"
            f"奖品：{prize}\n"
            f"消耗：{cost} 积分\n"
            f"开奖：{draw_str}\n"
            f"中奖人数：{wcnt}\n\n"
            f"{desc}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 参与抽奖", callback_data=f"join_lottery_{lid}")]
        ])
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ============================== 8. 老师触发 ==============================

async def _load_teachers(context):
    """缓存 60s 的老师列表"""
    cache = context.bot_data.setdefault("teacher_cache", {"time": 0, "data": []})
    now = _ts()
    if now - cache["time"] > 60:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT name, region, price_info, channel_msg_link FROM teachers",
            ) as cur:
                cache["data"] = await cur.fetchall()
        cache["time"] = now
    return cache["data"]


async def teacher_trigger_handler(update: Update, context):
    """监听消息：地区精准匹配 → 姓名模糊包含"""
    text = update.message.text.strip()
    if not text:
        return

    teachers = await _load_teachers(context)
    if not teachers:
        return

    # 优先：地区精准匹配
    region_hits = [t for t in teachers if t[1] and text == t[1]]
    if region_hits:
        lines = [f"📍 服务地区「{text}」的老师："]
        for i, t in enumerate(region_hits, 1):
            name, _, price, link = t
            if link:
                lines.append(f'{i}. <a href="{link}">{name}</a> — 💰 {price or "面议"}')
            else:
                lines.append(f"{i}. {name} — 💰 {price or '面议'}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    # 次优：姓名精准匹配（仅单独发送老师名字时触发）
    text_clean = text.strip().lower()
    for t in teachers:
        name, region, price, link = t
        if name and text_clean == name.lower():
            kb = None
            if link:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📎 查看详情", url=link)],
                ])
            await update.message.reply_text(
                f"👩‍🏫 <b>{name}</b>\n"
                f"📍 地区：{region or '未设置'}\n"
                f"💰 {price or '面议'}",
                reply_markup=kb,
                parse_mode="HTML",
            )
            return


# ============================== 注册函数 ==============================

def register_group_main(app) -> None:
    """主群所有 MessageHandler 注册入口"""
    # 签到（仅 2 字，不会触发活跃加分）
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^签到$"), sign_in_handler,
    ))

    # 三大排行榜
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^(今日排行|活跃排行|积分排行|邀请排行)$"),
        leaderboard_handler,
    ))

    # 排行榜翻页
    app.add_handler(CallbackQueryHandler(
        leaderboard_page_callback, pattern=r"^lb_(today|active|points|invite)_\d+$",
    ))

    # 邀请链接
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^邀请$"), invite_handler,
    ))

    # 管理员控分
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^(加积分|减积分)\s?\d+$") & is_admin,
        admin_points_handler,
    ))

    # 管理员禁言/解禁
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^禁言\s*\d+\s*$") & is_admin,
        mute_handler,
    ))
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^解禁\s*$") & is_admin,
        unmute_handler,
    ))

    # 查积分 / 积分兑换 / 抽奖列表
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^积分$"), my_points_handler,
    ))
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^积分兑换$"), shop_handler,
    ))
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.Regex(r"^抽奖$"), lottery_list_handler,
    ))

    # 老师地区/姓名自动触发（放最后，以免吃掉其他关键词）
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.TEXT & ~filters.COMMAND,
        teacher_trigger_handler,
    ))

    # 活跃加分（独立 handler 组，确保每条消息都能触发）
    app.add_handler(MessageHandler(
        (main_group | slave_group) & filters.TEXT & ~filters.COMMAND,
        active_points_handler,
    ), group=1)
