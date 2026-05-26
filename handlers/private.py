"""
普通用户私聊处理器 — 裂变溯源 / 积分兑换 / 抽奖参与
"""
import asyncio
import logging
from datetime import datetime

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CommandHandler, filters

from config import ADMIN_IDS, DB_PATH, GROUP_INVITE_LINK, CHANNEL_ID

logger = logging.getLogger(__name__)

# 防超卖并发锁
_purchase_lock = asyncio.Lock()


# ============================== 工具 ==============================

def _ts() -> int:
    return int(datetime.now().timestamp())


async def _bot_username(context) -> str:
    me = context.bot_data.get("bot_me")
    if not me:
        me = await context.bot.get_me()
        context.bot_data["bot_me"] = me
    return me.username


# ============================== 入口 /start ==============================

async def start_handler(update: Update, context):
    """/start — 欢迎 / 邀请裂变 / 积分兑换 / 抽奖参与"""
    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text(
            "欢迎！\n\n"
            "📌 常用指令：\n"
            "在群内发送「签到」每日打卡\n"
            "发送「积分排行」「邀请排行」查看榜单\n\n"
            "点击群内商品/抽奖按钮即可参与活动。",
        )
        return

    param = args[0]

    # --- 邀请裂变 /start invite_{id} ---
    if param.startswith("invite_"):
        parts = param.split("_", 1)
        if len(parts) < 2 or not parts[1].isdigit():
            await update.message.reply_text("无效的邀请链接。")
            return
        inviter_id = int(parts[1])
        if inviter_id == user.id:
            await update.message.reply_text("不可以自己邀请自己哦！")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id FROM invitations WHERE invitee_id = ?", (user.id,),
            ) as cur:
                if await cur.fetchone():
                    await update.message.reply_text("你已经在别人的邀请链路中了。")
                    return
            await db.execute(
                "INSERT INTO invitations (inviter_id, invitee_id, status, created_at) "
                "VALUES (?, ?, 'PENDING', ?)",
                (inviter_id, user.id, _ts()),
            )
            await db.commit()
            # 确保邀请人出现在 users 表
            await db.execute(
                "INSERT OR IGNORE INTO users (tg_id, joined_at) VALUES (?, ?)",
                (inviter_id, _ts()),
            )
            await db.commit()
        link = GROUP_INVITE_LINK or "（请联系管理员获取入群链接）"
        await update.message.reply_text(
            "🎉 欢迎加入我们！\n\n"
            f"请通过下方链接加入群组，进群后即可解锁完整功能：\n{link}\n\n"
            "进群后发送「签到」获取积分哦～",
        )
        return

    # --- 积分兑换 /start buy_{id} ---
    if param.startswith("buy_"):
        parts = param.split("_", 1)
        if len(parts) < 2 or not parts[1].isdigit():
            await update.message.reply_text("无效的商品链接。")
            return
        await _show_buy_panel(update, context, int(parts[1]))
        return

    # --- 抽奖参与 /start join_lottery_{id} ---
    if param.startswith("join_lottery_"):
        parts = param.rsplit("_", 1)
        if len(parts) < 2 or not parts[1].isdigit():
            await update.message.reply_text("无效的抽奖链接。")
            return
        await _handle_lottery_join(update, context, int(parts[1]))
        return

    await update.message.reply_text("未知的启动参数。")


# ============================== 积分兑换 ==============================

async def _show_buy_panel(update: Update, context, product_id: int):
    """查询商品并展示确认面板"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, description, price, stock, is_active FROM products WHERE id = ?",
            (product_id,),
        ) as cur:
            p = await cur.fetchone()

    if not p or not p[5]:
        await update.message.reply_text("该商品已不存在或已下架。")
        return

    pid, title, desc, price, stock = p[0], p[1], p[2], p[3], p[4]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 确认兑换", callback_data=f"confirm_buy_{pid}")],
        [InlineKeyboardButton("❌ 取消", callback_data="cancel_buy")],
    ])
    await update.message.reply_text(
        f"🛒 *积分兑换确认*\n\n"
        f"商品名称：{title}\n"
        f"商品详情：{desc}\n"
        f"所需积分：{price}\n"
        f"当前库存：{stock}\n\n"
        f"⚠️ 点击确认后将立刻扣除积分，确定兑换吗？",
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def buy_callback(update: Update, context):
    """群内「立即兑换」→ 引导私聊；私聊直接出面板"""
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_", 1)
    if len(parts) < 2 or not parts[1].isdigit():
        return
    product_id = int(parts[1])

    # 群聊 → 深链重定向
    if update.effective_chat.type != "private":
        bot = await _bot_username(context)
        link = f"https://t.me/{bot}?start=buy_{product_id}"
        await q.edit_message_text(
            "⬇️ 点击下方按钮前往私聊完成兑换：",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✈️ 前往私聊", url=link)],
            ]),
        )
        return

    # 私聊直接出面板（少数情况：私聊点到的场合）
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, description, price, stock, is_active FROM products WHERE id = ?",
            (product_id,),
        ) as cur:
            p = await cur.fetchone()
    if not p or not p[5]:
        await q.edit_message_text("该商品已不存在或已下架。")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 确认兑换", callback_data=f"confirm_buy_{p[0]}")],
        [InlineKeyboardButton("❌ 取消", callback_data="cancel_buy")],
    ])
    await q.edit_message_text(
        f"🛒 *积分兑换确认*\n\n"
        f"商品名称：{p[1]}\n"
        f"所需积分：{p[3]}\n"
        f"当前库存：{p[4]}\n\n"
        f"⚠️ 点击确认后将立刻扣除积分，确定兑换吗？",
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def confirm_buy_callback(update: Update, context):
    """原子扣分 + 减库存 + 管理员通知"""
    q = update.callback_query
    await q.answer()
    product_id = int(q.data.rsplit("_", 1)[-1])
    user = update.effective_user

    async with _purchase_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id, title, content_link, price, stock, is_active FROM products WHERE id = ?",
                (product_id,),
            ) as cur:
                p = await cur.fetchone()

            if not p or not p[5]:
                await q.edit_message_text("该商品已不存在或已下架。")
                return

            pid, title, link, price, stock = p[0], p[1], p[2], p[3], p[4]

            if stock <= 0:
                await q.edit_message_text("😢 该商品库存已售罄。")
                return

            async with db.execute(
                "SELECT points FROM users WHERE tg_id = ?", (user.id,),
            ) as cur:
                row = await cur.fetchone()
            user_pts = row[0] if row else 0

            if user_pts < price:
                await q.edit_message_text(
                    f"积分不足！你需要 {price} 积分，当前只有 {user_pts} 积分。",
                )
                return

            # 原子操作
            await db.execute(
                "UPDATE users SET points = points - ? WHERE tg_id = ?",
                (price, user.id),
            )
            await db.execute(
                "UPDATE products SET stock = stock - 1 WHERE id = ? AND stock > 0",
                (pid,),
            )
            await db.commit()

    # 交付内容
    content = link or "请联系管理员获取交付内容。"
    await q.edit_message_text(
        f"✅ *兑换成功！*\n\n"
        f"商品：{title}\n"
        f"交付内容：{content}\n\n"
        f"请保存好以上信息。",
        disable_web_page_preview=True,
        parse_mode="Markdown",
    )

    # 通知所有管理员
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📦 *新兑换通知*\n\n"
                f"商品：{title}\n"
                f"用户：{user.full_name}（ID: {user.id}）\n"
                f"交付内容：{content}\n\n"
                f"请及时联系用户完成交付。",
                disable_web_page_preview=True,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning("通知管理员 %d 失败: %s", admin_id, e)


async def cancel_buy_callback(update: Update, context):
    """取消兑换"""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("❌ 已取消兑换。")


# ============================== 抽奖参与 ==============================


async def _check_lottery_channels(user_id: int, bot) -> tuple[bool, list]:
    """检查用户是否已加入任一必需群组。返回 (通过, [(title, link)])"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id, title, invite_link FROM required_channels ORDER BY id",
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        return True, []

    for chat_id, title, link in rows:
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ("member", "administrator", "creator"):
                return True, []
        except Exception:
            pass  # Bot 无法检查就跳过

    # 用户不在任何一个里
    failed = []
    for chat_id, title, link in rows:
        if not link:
            try:
                link = await bot.export_chat_invite_link(chat_id=chat_id)
            except Exception:
                pass
        failed.append((title, link))
    return False, failed


async def _process_lottery_join(user_id: int, username: str, lottery_id: int, bot, reply_func):
    """抽奖参与核心逻辑。返回用户可见的提示文本，None=成功"""
    async with aiosqlite.connect(DB_PATH) as db:
        # 0. 检查抽奖功能是否开启
        async with db.execute("SELECT value FROM settings WHERE key = 'lottery_enabled'") as cur:
            row = await cur.fetchone()
            if not row or row[0] != "1":
                return "抽奖功能已关闭。"

        async with db.execute(
            "SELECT id, title, cost_points, is_active, max_participants, "
            "max_entries_per_user, min_msgs FROM lotteries WHERE id = ?",
            (lottery_id,),
        ) as cur:
            l = await cur.fetchone()

        if not l or not l[3]:
            return "该抽奖活动已结束。"

        lid, title, cost, _, max_ppl, max_entries, min_msgs = l

        # 1. 频道校验
        passed, failed_channels = await _check_lottery_channels(user_id, bot)
        if not passed:
            lines = ["请先加入以下群组后再参与抽奖："]
            for ch_title, ch_link in failed_channels:
                lines.append(f"• {ch_title}" + (f" ({ch_link})" if ch_link else ""))
            return "\n".join(lines)

        # 2. 最低发言数
        if min_msgs > 0:
            async with db.execute(
                "SELECT total_msgs FROM users WHERE tg_id = ?", (user_id,),
            ) as cur:
                row = await cur.fetchone()
                msgs = row[0] if row else 0
            if msgs < min_msgs:
                return f"您在群内需发言 {min_msgs} 条才能参与抽奖，当前已发言 {msgs} 条。"

        # 3. 重复/多 entry 检查
        async with db.execute(
            "SELECT entries FROM lottery_participants WHERE lottery_id = ? AND tg_id = ?",
            (lid, user_id),
        ) as cur:
            row = await cur.fetchone()
            current_entries = row[0] if row else 0

        if max_entries > 0 and current_entries >= max_entries:
            return f"您已达到参与上限（{max_entries} 次），无法继续参与。"

        # 4. 参与人数上限
        if max_ppl > 0:
            async with db.execute(
                "SELECT COUNT(*) FROM lottery_participants WHERE lottery_id = ?",
                (lid,),
            ) as cur:
                count = (await cur.fetchone())[0]
            if count >= max_ppl:
                return "该抽奖已满员，无法继续参与。"

        # 5. 积分校验
        async with db.execute(
            "SELECT points FROM users WHERE tg_id = ?", (user_id,),
        ) as cur:
            row = await cur.fetchone()
            user_pts = row[0] if row else 0

        if user_pts < cost:
            return f"积分不足！参与需要 {cost} 积分，当前只有 {user_pts} 积分。"

        # 6. 扣分 + 记录
        await db.execute(
            "UPDATE users SET points = points - ? WHERE tg_id = ?",
            (cost, user_id),
        )
        await db.execute(
            "INSERT INTO lottery_participants (lottery_id, tg_id, entries) VALUES (?, ?, 1) "
            "ON CONFLICT(lottery_id, tg_id) DO UPDATE SET entries = entries + 1",
            (lid, user_id),
        )
        # 更新 username
        await db.execute(
            "UPDATE users SET username = ? WHERE tg_id = ?",
            (username, user_id),
        )
        await db.commit()

    new_entries = current_entries + 1
    remaining = max_entries - new_entries if max_entries > 0 else "不限"
    return f"🎯 参与成功！您已参与 {new_entries} 次，剩余 {remaining} 次。"
    # 返回 None 以外的字符串 = 成功提示


async def _handle_lottery_join(update: Update, context, lottery_id: int):
    """处理抽奖参与（私聊 /start 深链入口）"""
    user = update.effective_user
    result = await _process_lottery_join(
        user.id, user.full_name, lottery_id, context.bot, None,
    )
    if result:
        await update.message.reply_text(result, parse_mode="Markdown")


async def join_lottery_callback(update: Update, context):
    """群内或私聊点击参与抽奖按钮 — 直接处理，不跳转"""
    q = update.callback_query
    parts = q.data.rsplit("_", 1)
    if len(parts) < 2 or not parts[1].isdigit():
        await q.answer()
        return
    lottery_id = int(parts[1])
    user = update.effective_user

    result = await _process_lottery_join(
        user.id, user.full_name, lottery_id, context.bot, q,
    )

    if result.startswith("🎯"):
        # 成功 → 小窗口提示，消息保留抽奖信息并追加参与人统计
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT title, description, prize, cost_points, draw_time, "
                "max_participants, winner_count, max_entries_per_user, min_msgs "
                "FROM lotteries WHERE id = ?", (lottery_id,),
            ) as cur:
                l = await cur.fetchone()
            async with db.execute(
                "SELECT COUNT(*), COALESCE(SUM(entries), 0) FROM lottery_participants WHERE lottery_id = ?",
                (lottery_id,),
            ) as cur:
                ppl, total_entries = await cur.fetchone()

        if l:
            draw_str = datetime.fromtimestamp(l[4]).strftime("%Y-%m-%d %H:%M")
            parts_list = []
            if l[5] > 0:
                parts_list.append(f"限 {l[5]} 人")
            if l[7] > 0:
                parts_list.append(f"每人限 {l[7]} 次")
            if l[8] > 0:
                parts_list.append(f"需发言 {l[8]} 条")
            limit_str = "、".join(parts_list) if parts_list else "无限制"

            text = (
                f"🎁 *新抽奖上架！*\n\n"
                f"标题：{l[0]}\n"
                f"详情：{l[1]}\n"
                f"奖品：{l[2]}\n"
                f"参与消耗：{l[3]} 积分\n"
                f"开奖时间：{draw_str}\n"
                f"限制：{limit_str}\n"
                f"中奖人数：{l[6]}\n\n"
                f"👥 已有 {ppl} 人参与（共 {total_entries} 次）\n\n"
                f"点击下方按钮参与抽奖 👇"
            )
            await q.answer("🎯 参与成功！", show_alert=False)
            await q.edit_message_text(text, reply_markup=q.message.reply_markup, parse_mode="Markdown")
        else:
            await q.answer("抽奖已结束。", show_alert=True)
    else:
        # 失败 → 弹窗提示
        await q.answer(result, show_alert=True)


# ============================== 注册函数 ==============================

def register_private(app) -> None:
    """私聊所有 handler 注册入口"""
    pv = filters.ChatType.PRIVATE

    # /start 路由（欢迎 / 裂变 / 兑换 / 抽奖）
    app.add_handler(CommandHandler("start", start_handler, filters=pv))

    # 商品立即兑换 → 引导私聊
    app.add_handler(CallbackQueryHandler(buy_callback, pattern=r"^buy_\d+$"))

    # 确认 / 取消兑换
    app.add_handler(CallbackQueryHandler(confirm_buy_callback, pattern=r"^confirm_buy_\d+$"))
    app.add_handler(CallbackQueryHandler(cancel_buy_callback, pattern=r"^cancel_buy$"))

    # 抽奖参与 → 引导私聊
    app.add_handler(CallbackQueryHandler(join_lottery_callback, pattern=r"^join_lottery_\d+$"))
