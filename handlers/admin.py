"""
管理员私聊后台 — ConversationHandler + InlineKeyboard 全交互
"""
import json
import logging
from datetime import datetime

import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import ADMIN_IDS, CHANNEL_ID, DB_PATH, MAIN_GROUP_ID

logger = logging.getLogger(__name__)

# ============================== 状态定义 ==============================
(
    MAIN_MENU,
    PRODUCT_MENU,
    PRODUCT_ADD_NAME,
    PRODUCT_ADD_DESC,
    PRODUCT_ADD_LINK,
    PRODUCT_ADD_PRICE,
    PRODUCT_ADD_STOCK,
    PRODUCT_REMOVE_SELECT,
    LOTTERY_MENU,
    LOTTERY_ADD_TITLE,
    LOTTERY_ADD_DESC,
    LOTTERY_ADD_PRIZE,
    LOTTERY_ADD_COST,
    LOTTERY_ADD_DRAW_TIME,
    LOTTERY_ADD_TARGET,
    LOTTERY_REMOVE_SELECT,
    TEACHER_MENU,
    TEACHER_ADD_NAME,
    TEACHER_ADD_REGION,
    TEACHER_ADD_PRICE,
    TEACHER_ADD_PHOTO,
    TEACHER_REMOVE_SELECT,
    TEACHER_ADD_CONTACT,
    REQUIRED_CHANNEL_MENU,
    REQUIRED_CHANNEL_ADD_ID,
    REQUIRED_CHANNEL_ADD_TITLE,
    REQUIRED_CHANNEL_ADD_LINK,
    LOTTERY_ADD_MAX_PARTICIPANTS,
    LOTTERY_ADD_WINNER_COUNT,
    LOTTERY_ADD_MAX_ENTRIES,
    LOTTERY_ADD_MIN_MSGS,
    LOTTERY_DETAIL,
    LOTTERY_PARTICIPANTS,
    POINTS_MENU,
    POINTS_EDIT_USER,
    POINTS_EDIT_AMOUNT,
    PRODUCT_EDIT_SELECT,
    PRODUCT_EDIT_FIELD,
    PRODUCT_EDIT_VALUE,
    LOTTERY_EDIT_FIELD,
    LOTTERY_EDIT_VALUE,
    TEACHER_PROMOTE_MENU,
    TEACHER_PROMOTE_INTERVAL,
    TEACHER_PROMOTE_SHOW,
    LOTTERY_ADD_PHOTO,
    LOTTERY_CONFIRM,
) = range(46)

# ============================== 键盘构建 ==============================


def _btn(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def main_kb():
    return InlineKeyboardMarkup([
        [_btn("🛒 商品管理", "admin_product"), _btn("🎁 抽奖管理", "admin_lottery")],
        [_btn("👭 老师上榜", "admin_teacher"), _btn("🛡️ 风控看板", "admin_risk")],
        [_btn("💰 积分管理", "admin_points")],
    ])


def product_kb():
    return InlineKeyboardMarkup([
        [_btn("➕ 上架商品", "admin_product_add"), _btn("❌ 下架商品", "admin_product_remove")],
        [_btn("✏️ 编辑商品", "admin_product_edit")],
        [_btn("🔙 返回主菜单", "admin_main")],
    ])


def lottery_kb():
    return InlineKeyboardMarkup([
        [_btn("➕ 创建抽奖", "admin_lottery_add"), _btn("📋 抽奖列表", "admin_lottery_list")],
        [_btn("🔙 返回主菜单", "admin_main")],
    ])


def teacher_kb():
    return InlineKeyboardMarkup([
        [_btn("➕ 新增上榜", "admin_teacher_add"), _btn("❌ 老师下榜", "admin_teacher_remove")],
        [_btn("📢 轮播设置", "admin_teacher_promote")],
        [_btn("🔙 返回主菜单", "admin_main")],
    ])


def teacher_photo_kb():
    return InlineKeyboardMarkup([
        [_btn("✅ 确认上传", "admin_teacher_confirm")],
        [_btn("🔙 返回上级", "admin_teacher")],
    ])


# ============================== 入口 & 通用 ==============================


async def admin_entry(update: Update, context):
    await update.message.reply_text(
        "🔐 欢迎进入管理后台，请选择操作：",
        reply_markup=main_kb(),
    )
    return MAIN_MENU


async def go_main(update: Update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🔐 欢迎进入管理后台，请选择操作：", reply_markup=main_kb())
    return MAIN_MENU


async def cancel(update: Update, context):
    text = "已退出管理后台 👋"
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(text)
        except Exception:
            try:
                await update.callback_query.delete_message()
            except Exception:
                pass
            await context.bot.send_message(
                chat_id=update.callback_query.message.chat_id, text=text
            )
    elif update.message:
        await update.message.reply_text(text)
    context.user_data.clear()
    return ConversationHandler.END


# ============================== 商品管理 ==============================


async def product_menu(update: Update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🛒 商品管理", reply_markup=product_kb())
    return PRODUCT_MENU


async def product_add_start(update: Update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("请输入商品名称：")
    return PRODUCT_ADD_NAME


async def product_add_name(update: Update, context):
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("名称不能为空，请重新输入：")
        return PRODUCT_ADD_NAME
    context.user_data["prod_name"] = name
    await update.message.reply_text("请输入商品详情：")
    return PRODUCT_ADD_DESC


async def product_add_desc(update: Update, context):
    context.user_data["prod_desc"] = update.message.text.strip()
    await update.message.reply_text("请输入兑换后发放的链接或用户名：")
    return PRODUCT_ADD_LINK


async def product_add_link(update: Update, context):
    context.user_data["prod_link"] = update.message.text.strip()
    await update.message.reply_text("请输入所需积分（正整数）：")
    return PRODUCT_ADD_PRICE


async def product_add_price(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("积分必须为正整数，请重新输入：")
        return PRODUCT_ADD_PRICE
    context.user_data["prod_price"] = int(text)
    await update.message.reply_text("请输入库存数量（正整数）：")
    return PRODUCT_ADD_STOCK


async def product_add_stock(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("库存必须为正整数，请重新输入：")
        return PRODUCT_ADD_STOCK
    context.user_data["prod_stock"] = int(text)

    data = context.user_data
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO products (title, description, content_link, price, stock) VALUES (?, ?, ?, ?, ?)",
            (data["prod_name"], data["prod_desc"], data["prod_link"],
             data["prod_price"], data["prod_stock"]),
        )
        await db.commit()
    logger.info("管理员上架商品: %s", data["prod_name"])

    await update.message.reply_text(
        f"✅ 商品上架成功！\n"
        f"名称：{data['prod_name']}\n"
        f"积分：{data['prod_price']}\n"
        f"库存：{data['prod_stock']}",
        reply_markup=product_kb(),
    )
    return PRODUCT_MENU


async def product_remove_list(update: Update, context):
    q = update.callback_query
    await q.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, price FROM products WHERE is_active = 1 ORDER BY id",
        ) as cur:
            products = await cur.fetchall()

    if not products:
        await q.edit_message_text("暂无上架商品。", reply_markup=product_kb())
        return PRODUCT_MENU

    kb = [[_btn(f"❌ {p[1]}（{p[2]} 积分）", f"admin_remove_product_{p[0]}")] for p in products]
    kb.append([_btn("🔙 返回", "admin_product")])
    await q.edit_message_text("请选择要下架的商品：", reply_markup=InlineKeyboardMarkup(kb))
    return PRODUCT_REMOVE_SELECT


async def product_remove_execute(update: Update, context):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE products SET is_active = 0 WHERE id = ?", (pid,))
        await db.commit()
    logger.info("管理员下架商品 ID=%d", pid)
    await q.edit_message_text("✅ 已下架该商品。", reply_markup=product_kb())
    return PRODUCT_MENU


# ============================== 商品编辑 ==============================


async def product_edit_start(update: Update, context):
    q = update.callback_query
    await q.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, price FROM products WHERE is_active = 1 ORDER BY id",
        ) as cur:
            products = await cur.fetchall()
    if not products:
        await q.edit_message_text("暂无上架商品。", reply_markup=product_kb())
        return PRODUCT_MENU
    kb = [[_btn(f"✏️ {p[1]}（{p[2]} 积分）", f"admin_edit_product_{p[0]}")] for p in products]
    kb.append([_btn("🔙 返回", "admin_product")])
    await q.edit_message_text("请选择要编辑的商品：", reply_markup=InlineKeyboardMarkup(kb))
    return PRODUCT_EDIT_SELECT


async def product_edit_show(update: Update, context):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split("_")[-1])
    context.user_data["edit_pid"] = pid
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT title, description, content_link, price, stock FROM products WHERE id = ?",
            (pid,),
        ) as cur:
            p = await cur.fetchone()
    if not p:
        await q.edit_message_text("商品不存在。", reply_markup=product_kb())
        return PRODUCT_MENU
    text = (
        f"✏️ *编辑商品*\n\n"
        f"名称：{p[0]}\n"
        f"描述：{p[1]}\n"
        f"链接：{p[2] or '无'}\n"
        f"价格：{p[3]} 积分\n"
        f"库存：{p[4]}"
    )
    kb = [
        [_btn("📝 改名称", "admin_edit_prod_title")],
        [_btn("📝 改描述", "admin_edit_prod_desc")],
        [_btn("📝 改链接", "admin_edit_prod_link")],
        [_btn("📝 改价格", "admin_edit_prod_price"), _btn("📝 改库存", "admin_edit_prod_stock")],
        [_btn("✅ 完成", "admin_product")],
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return PRODUCT_EDIT_FIELD


async def product_edit_field(update: Update, context):
    q = update.callback_query
    await q.answer()
    field = q.data.split("_")[-1]
    context.user_data["edit_pfield"] = field
    names = {"title": "名称", "desc": "描述", "link": "链接", "price": "价格", "stock": "库存"}
    await q.edit_message_text(f"请输入新的{names.get(field, field)}：")
    return PRODUCT_EDIT_VALUE


async def product_edit_value(update: Update, context):
    text = update.message.text.strip()
    field = context.user_data["edit_pfield"]
    pid = context.user_data["edit_pid"]
    col_map = {"title": "title", "desc": "description", "link": "content_link",
               "price": "price", "stock": "stock"}
    col = col_map.get(field)
    if not col:
        return PRODUCT_MENU
    if field in ("price", "stock"):
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("请输入正整数！")
            return PRODUCT_EDIT_VALUE
        val = int(text)
    else:
        if not text:
            await update.message.reply_text("内容不能为空！")
            return PRODUCT_EDIT_VALUE
        val = text
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE products SET {col} = ? WHERE id = ?", (val, pid))
        await db.commit()
    logger.info("管理员编辑商品 %d: %s=%s", pid, col, val)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT title, description, content_link, price, stock FROM products WHERE id = ?",
            (pid,),
        ) as cur:
            p = await cur.fetchone()
    text = (
        f"✏️ *编辑商品*（已保存 ✅）\n\n"
        f"名称：{p[0]}\n"
        f"描述：{p[1]}\n"
        f"链接：{p[2] or '无'}\n"
        f"价格：{p[3]} 积分\n"
        f"库存：{p[4]}"
    )
    kb = [
        [_btn("📝 改名称", "admin_edit_prod_title")],
        [_btn("📝 改描述", "admin_edit_prod_desc")],
        [_btn("📝 改链接", "admin_edit_prod_link")],
        [_btn("📝 改价格", "admin_edit_prod_price"), _btn("📝 改库存", "admin_edit_prod_stock")],
        [_btn("✅ 完成", "admin_product")],
    ]
    await update.message.reply_text("✅ 已更新！\n" + text, reply_markup=InlineKeyboardMarkup(kb))
    return PRODUCT_EDIT_FIELD


# ============================== 抽奖管理 ==============================


async def lottery_menu(update: Update, context):
    q = update.callback_query
    await q.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'lottery_enabled'") as cur:
            row = await cur.fetchone()
            enabled = row and row[0] == "1"
    status = "🟢 开启" if enabled else "🔴 关闭"
    kb = InlineKeyboardMarkup([
        [_btn("➕ 创建抽奖", "admin_lottery_add"), _btn("📋 抽奖列表", "admin_lottery_list")],
        [_btn(f"🎲 抽奖状态: {status}", "admin_lottery_toggle")],
        [_btn("🔙 返回主菜单", "admin_main")],
    ])
    await q.edit_message_text("🎁 抽奖管理", reply_markup=kb)
    return LOTTERY_MENU


async def lottery_add_start(update: Update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("请输入抽奖标题：")
    return LOTTERY_ADD_TITLE


async def lottery_add_title(update: Update, context):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("标题不能为空，请重新输入：")
        return LOTTERY_ADD_TITLE
    context.user_data["lot_title"] = text
    await update.message.reply_text("请输入抽奖详情描述：")
    return LOTTERY_ADD_DESC


async def lottery_add_desc(update: Update, context):
    context.user_data["lot_desc"] = update.message.text.strip()
    await update.message.reply_text("请输入奖品描述：")
    return LOTTERY_ADD_PRIZE


async def lottery_add_prize(update: Update, context):
    context.user_data["lot_prize"] = update.message.text.strip()
    await update.message.reply_text("请输入参与消耗积分（正整数）：")
    return LOTTERY_ADD_COST


async def lottery_add_cost(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("积分必须为正整数，请重新输入：")
        return LOTTERY_ADD_COST
    context.user_data["lot_cost"] = int(text)
    await update.message.reply_text("请输入开奖时间（格式：YYYY-MM-DD HH:MM）：")
    return LOTTERY_ADD_DRAW_TIME


async def lottery_add_draw_time(update: Update, context):
    text = update.message.text.strip()
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        ts = int(dt.timestamp())
        if ts <= datetime.now().timestamp():
            await update.message.reply_text("开奖时间必须在未来，请重新输入：")
            return LOTTERY_ADD_DRAW_TIME
        context.user_data["lot_draw_time"] = ts
    except ValueError:
        await update.message.reply_text("时间格式错误，请使用 YYYY-MM-DD HH:MM 格式：")
        return LOTTERY_ADD_DRAW_TIME

    await update.message.reply_text("请输入指定必中用户的 Telegram ID（输入 0 表示不指定）：")
    return LOTTERY_ADD_TARGET


async def lottery_add_target(update: Update, context):
    text = update.message.text.strip()
    if not text.lstrip("-").isdigit():
        await update.message.reply_text("请输入有效的数字 ID，输入 0 表示不指定：")
        return LOTTERY_ADD_TARGET
    context.user_data["lot_target"] = int(text)

    await update.message.reply_text("请输入最大参与人数（输入 0 表示不限制）：")
    return LOTTERY_ADD_MAX_PARTICIPANTS


async def lottery_add_max_participants(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("请输入有效数字，输入 0 表示不限制：")
        return LOTTERY_ADD_MAX_PARTICIPANTS
    context.user_data["lot_max_ppl"] = int(text)
    await update.message.reply_text("请输入中奖人数（默认 1）：")
    return LOTTERY_ADD_WINNER_COUNT


async def lottery_add_winner_count(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("中奖人数必须为正整数，请重新输入：")
        return LOTTERY_ADD_WINNER_COUNT
    context.user_data["lot_winner_cnt"] = int(text)
    await update.message.reply_text("请输入每人最大参与次数（输入 0 表示不限制）：")
    return LOTTERY_ADD_MAX_ENTRIES


async def lottery_add_max_entries(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("请输入有效数字，输入 0 表示不限制：")
        return LOTTERY_ADD_MAX_ENTRIES
    context.user_data["lot_max_entries"] = int(text)
    await update.message.reply_text("请输入最低发言数（输入 0 表示不限制）：")
    return LOTTERY_ADD_MIN_MSGS


async def lottery_add_min_msgs(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("请输入有效数字，输入 0 表示不限制：")
        return LOTTERY_ADD_MIN_MSGS

    context.user_data["lot_min_msgs"] = int(text)

    kb = InlineKeyboardMarkup([
        [_btn("⏭ 跳过图片", "admin_lottery_skip_photo")],
        [_btn("❌ 取消创建", "admin_cancel")],
    ])
    await update.message.reply_text(
        "请发送抽奖展示图片（可选），或点击跳过：",
        reply_markup=kb,
    )
    return LOTTERY_ADD_PHOTO


async def lottery_add_photo(update: Update, context):
    """收集抽奖图片，然后显示预览"""
    if update.message and update.message.photo:
        context.user_data["lot_photo"] = update.message.photo[-1].file_id
    return await _lottery_show_preview(update, context, is_callback=False)


async def lottery_skip_photo(update: Update, context):
    """跳过图片，直接显示预览"""
    q = update.callback_query
    await q.answer()
    context.user_data.pop("lot_photo", None)
    return await _lottery_show_preview(update, context, is_callback=True)


async def _lottery_show_preview(update: Update, context, is_callback: bool = False):
    """显示抽奖信息预览 + 确认发送"""
    data = context.user_data

    draw_str = datetime.fromtimestamp(data["lot_draw_time"]).strftime("%Y-%m-%d %H:%M")
    parts = []
    if data.get("lot_max_ppl", 0) > 0:
        parts.append(f"限 {data['lot_max_ppl']} 人")
    if data.get("lot_max_entries", 0) > 0:
        parts.append(f"每人限 {data['lot_max_entries']} 次")
    if data.get("lot_min_msgs", 0) > 0:
        parts.append(f"需发言 {data['lot_min_msgs']} 条")
    limit_str = "、".join(parts) if parts else "无限制"

    text = (
        f"🎁 *新抽奖上架！*\n\n"
        f"标题：{data['lot_title']}\n"
        f"详情：{data['lot_desc']}\n"
        f"奖品：{data['lot_prize']}\n"
        f"参与消耗：{data['lot_cost']} 积分\n"
        f"开奖时间：{draw_str}\n"
        f"限制：{limit_str}\n"
        f"中奖人数：{data['lot_winner_cnt']}\n\n"
        f"确认发送以上内容到群组？"
    )

    kb = InlineKeyboardMarkup([
        [_btn("✅ 确认发送", "admin_lottery_confirm")],
        [_btn("❌ 取消", "admin_cancel")],
    ])

    photo = data.get("lot_photo")
    if is_callback:
        q = update.callback_query
        if photo:
            await q.edit_message_media(
                InputMediaPhoto(media=photo, caption=text),
                reply_markup=kb,
            )
        else:
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        if photo:
            await update.message.reply_photo(photo=photo, caption=text, reply_markup=kb, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

    return LOTTERY_CONFIRM


async def lottery_confirm_send(update: Update, context):
    """确认发送 → 写入 DB + 推送到主群"""
    q = update.callback_query
    await q.answer()

    data = context.user_data

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO lotteries (title, description, prize, cost_points, draw_time, "
            "target_winner_id, max_participants, winner_count, max_entries_per_user, min_msgs, "
            "photo_file_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data["lot_title"], data["lot_desc"], data["lot_prize"],
             data["lot_cost"], data["lot_draw_time"], data.get("lot_target", 0),
             data.get("lot_max_ppl", 0), data["lot_winner_cnt"],
             data.get("lot_max_entries", 0), data.get("lot_min_msgs", 0),
             data.get("lot_photo", "")),
        )
        lid = cursor.lastrowid
        await db.commit()

    logger.info("管理员创建抽奖: %s", data["lot_title"])

    draw_str = datetime.fromtimestamp(data["lot_draw_time"]).strftime("%Y-%m-%d %H:%M")
    parts = []
    if data.get("lot_max_ppl", 0) > 0:
        parts.append(f"限 {data['lot_max_ppl']} 人")
    if data.get("lot_max_entries", 0) > 0:
        parts.append(f"每人限 {data['lot_max_entries']} 次")
    if data.get("lot_min_msgs", 0) > 0:
        parts.append(f"需发言 {data['lot_min_msgs']} 条")
    limit_str = "、".join(parts) if parts else "无限制"

    push_text = (
        f"🎁 *新抽奖上架！*\n\n"
        f"标题：{data['lot_title']}\n"
        f"详情：{data['lot_desc']}\n"
        f"奖品：{data['lot_prize']}\n"
        f"参与消耗：{data['lot_cost']} 积分\n"
        f"开奖时间：{draw_str}\n"
        f"限制：{limit_str}\n"
        f"中奖人数：{data['lot_winner_cnt']}\n\n"
        f"点击下方按钮参与抽奖 👇"
    )

    try:
        bot_me = await context.bot.get_me()
        join_link = f"https://t.me/{bot_me.username}?start=join_lottery_{lid}"
        photo = data.get("lot_photo")
        if photo:
            await context.bot.send_photo(
                MAIN_GROUP_ID, photo=photo, caption=push_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎯 参与抽奖", url=join_link)],
                ]),
                parse_mode="Markdown",
            )
        else:
            await context.bot.send_message(
                MAIN_GROUP_ID, push_text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎯 参与抽奖", url=join_link)],
                ]),
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.warning("抽奖推送主群失败: %s", e)

    success_text = (
        f"✅ 抽奖创建成功！\n"
        f"标题：{data['lot_title']}\n"
        f"奖品：{data['lot_prize']}\n"
        f"开奖时间：{draw_str}"
    )
    try:
        await q.edit_message_text(success_text, reply_markup=lottery_kb())
    except Exception:
        await q.delete_message()
        await context.bot.send_message(
            chat_id=q.message.chat_id, text=success_text, reply_markup=lottery_kb()
        )
    return LOTTERY_MENU


async def lottery_list(update: Update, context):
    """显示所有抽奖列表（含已结束）"""
    q = update.callback_query
    await q.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT l.id, l.title, l.is_active, l.draw_time, "
            "(SELECT COUNT(*) FROM lottery_participants WHERE lottery_id = l.id) AS cnt "
            "FROM lotteries l ORDER BY l.id DESC",
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await q.edit_message_text("暂无抽奖记录。", reply_markup=lottery_kb())
        return LOTTERY_MENU

    kb = []
    for rid, title, active, draw_ts, ppl_count in rows:
        status = "🟢" if active else "🔴"
        label = f"{status} {title} ({ppl_count}人)"
        kb.append([_btn(label, f"admin_lottery_detail_{rid}")])

    kb.append([_btn("🔙 返回", "admin_lottery")])
    await q.edit_message_text("📋 *抽奖列表*", reply_markup=InlineKeyboardMarkup(kb))
    return LOTTERY_DETAIL


async def lottery_detail(update: Update, context):
    """抽奖详情页"""
    q = update.callback_query
    await q.answer()
    lid = int(q.data.split("_")[-1])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, description, prize, cost_points, draw_time, "
            "target_winner_id, max_participants, winner_count, max_entries_per_user, "
            "min_msgs, is_active FROM lotteries WHERE id = ?", (lid,),
        ) as cur:
            l = await cur.fetchone()
        async with db.execute(
            "SELECT COUNT(*) FROM lottery_participants WHERE lottery_id = ?", (lid,),
        ) as cur:
            total_ppl = (await cur.fetchone())[0]

    if not l:
        await q.edit_message_text("抽奖不存在。", reply_markup=lottery_kb())
        return LOTTERY_MENU

    lid, title, desc, prize, cost, draw_ts, target, max_ppl, wcnt, max_ent, min_msg, active = l
    draw_str = datetime.fromtimestamp(draw_ts).strftime("%Y-%m-%d %H:%M")
    status = "🟢 进行中" if active else "🔴 已结束"

    text = (
        f"📋 *{title}*\n\n"
        f"状态：{status}\n"
        f"详情：{desc}\n"
        f"奖品：{prize}\n"
        f"消耗：{cost} 积分\n"
        f"开奖：{draw_str}\n"
        f"参与人数：{total_ppl}\n"
        f"人数上限：{'不限' if max_ppl == 0 else max_ppl}\n"
        f"每人上限：{'不限' if max_ent == 0 else f'{max_ent} 次'}\n"
        f"中奖人数：{wcnt}\n"
        f"最低发言：{'不限' if min_msg == 0 else f'{min_msg} 条'}\n"
        f"暗箱 ID：{target if target else '无'}"
    )

    kb = []
    if active:
        kb.append([_btn("❌ 下架", f"admin_remove_lottery_{lid}")])
    kb.append([_btn("✏️ 编辑", f"admin_edit_lottery_{lid}")])
    kb.append([_btn("👥 查看参与者", f"admin_lottery_ppl_{lid}")])
    kb.append([_btn("🔙 返回列表", "admin_lottery_list")])

    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return LOTTERY_PARTICIPANTS


async def lottery_participants_view(update: Update, context):
    """查看抽奖参与者列表"""
    q = update.callback_query
    await q.answer()
    lid = int(q.data.split("_")[-1])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT lp.tg_id, u.username, lp.entries FROM lottery_participants lp "
            "LEFT JOIN users u ON u.tg_id = lp.tg_id "
            "WHERE lp.lottery_id = ? ORDER BY lp.entries DESC", (lid,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await q.edit_message_text("暂无参与者。",
            reply_markup=InlineKeyboardMarkup([[_btn("🔙 返回", f"admin_lottery_detail_{lid}")]]))
        return LOTTERY_PARTICIPANTS

    lines = [f"👥 *参与者列表*（共 {len(rows)} 人）\n"]
    for i, (tg_id, uname, entries) in enumerate(rows, 1):
        display = f"@{uname}" if uname else f"用户{tg_id}"
        lines.append(f"{i}. {display} — {entries} 次")

    text = "\n".join(lines[:42])  # 避免消息超长
    if len(lines) > 42:
        text += f"\n… 还有 {len(rows) - 40} 人"

    await q.edit_message_text(text,
        reply_markup=InlineKeyboardMarkup([[_btn("🔙 返回", f"admin_lottery_detail_{lid}")]]))
    return LOTTERY_PARTICIPANTS


async def lottery_toggle(update: Update, context):
    """开/关抽奖功能"""
    q = update.callback_query
    await q.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'lottery_enabled'") as cur:
            row = await cur.fetchone()
        new_val = "0" if (row and row[0] == "1") else "1"
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('lottery_enabled', ?)", (new_val,))
        await db.commit()
    logger.info("抽奖功能 %s", "开启" if new_val == "1" else "关闭")
    return await lottery_menu(update, context)


async def lottery_remove_execute(update: Update, context):
    q = update.callback_query
    await q.answer()
    lid = int(q.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE lotteries SET is_active = 0 WHERE id = ?", (lid,))
        await db.commit()
    logger.info("管理员下架抽奖 ID=%d", lid)
    return await lottery_list(update, context)


# ============================== 抽奖编辑 ==============================


async def lottery_edit_show(update: Update, context):
    q = update.callback_query
    await q.answer()
    lid = int(q.data.split("_")[-1])
    context.user_data["edit_lid"] = lid
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT title, description, prize, cost_points FROM lotteries WHERE id = ?", (lid,),
        ) as cur:
            l = await cur.fetchone()
    if not l:
        return await lottery_detail(update, context)
    text = (
        f"✏️ *编辑抽奖*\n\n"
        f"标题：{l[0]}\n"
        f"描述：{l[1]}\n"
        f"奖品：{l[2]}\n"
        f"消耗：{l[3]} 积分"
    )
    kb = [
        [_btn("📝 改标题", "admin_edit_lot_title")],
        [_btn("📝 改描述", "admin_edit_lot_desc")],
        [_btn("📝 改奖品", "admin_edit_lot_prize")],
        [_btn("📝 改消耗", "admin_edit_lot_cost")],
        [_btn("✅ 完成", f"admin_lottery_detail_{lid}")],
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return LOTTERY_EDIT_FIELD


async def lottery_edit_field(update: Update, context):
    q = update.callback_query
    await q.answer()
    field = q.data.split("_")[-1]
    context.user_data["edit_lfield"] = field
    names = {"title": "标题", "desc": "描述", "prize": "奖品", "cost": "消耗积分"}
    await q.edit_message_text(f"请输入新的{names.get(field, field)}：")
    return LOTTERY_EDIT_VALUE


async def lottery_edit_value(update: Update, context):
    text = update.message.text.strip()
    field = context.user_data["edit_lfield"]
    lid = context.user_data["edit_lid"]
    col_map = {"title": "title", "desc": "description", "prize": "prize", "cost": "cost_points"}
    col = col_map.get(field)
    if not col:
        return LOTTERY_PARTICIPANTS
    if field == "cost":
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("请输入正整数！")
            return LOTTERY_EDIT_VALUE
        val = int(text)
    else:
        if not text:
            await update.message.reply_text("内容不能为空！")
            return LOTTERY_EDIT_VALUE
        val = text
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE lotteries SET {col} = ? WHERE id = ?", (val, lid))
        await db.commit()
    logger.info("管理员编辑抽奖 %d: %s=%s", lid, col, val)
    await update.message.reply_text("✅ 已保存！",
        reply_markup=InlineKeyboardMarkup([[_btn("🔙 返回详情", f"admin_lottery_detail_{lid}")]]))
    return LOTTERY_PARTICIPANTS


# ============================== 积分管理 ==============================


async def _build_points_menu_text_kb():
    """构建积分管理菜单的文本和键盘"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT tg_id, username, points FROM users ORDER BY points DESC LIMIT 20",
        ) as cur:
            top = await cur.fetchall()

    lines = ["💰 *积分排行榜 Top 20*\n"]
    for i, (uid, uname, pts) in enumerate(top, 1):
        display = f"@{uname}" if uname else f"用户{uid}"
        lines.append(f"{i}. {display} — {pts} 分")

    kb = [
        [_btn("➕ 加积分", "admin_points_add"), _btn("➖ 减积分", "admin_points_sub")],
        [_btn("🔙 返回主菜单", "admin_main")],
    ]
    return "\n".join(lines) if top else "暂无积分数据。", InlineKeyboardMarkup(kb)


async def points_menu(update: Update, context):
    text, kb = await _build_points_menu_text_kb()
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text(text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)
    return POINTS_MENU


async def points_edit_start(update: Update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["points_action"] = "add" if "add" in q.data else "sub"
    await q.edit_message_text("请输入用户 Telegram ID：")
    return POINTS_EDIT_USER


async def points_edit_user(update: Update, context):
    text = update.message.text.strip()
    if not text.lstrip("-").isdigit():
        await update.message.reply_text("请输入有效的数字 ID：")
        return POINTS_EDIT_USER
    context.user_data["points_tg_id"] = int(text)

    verb = "增加" if context.user_data["points_action"] == "add" else "扣除"
    await update.message.reply_text(f"请输入要{verb}的积分数量：")
    return POINTS_EDIT_AMOUNT


async def points_edit_amount(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("积分数量必须为正整数，请重新输入：")
        return POINTS_EDIT_AMOUNT

    amount = int(text)
    action = context.user_data["points_action"]
    tg_id = context.user_data["points_tg_id"]

    points = amount if action == "add" else -amount
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT points FROM users WHERE tg_id = ?", (tg_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            new_pts = max(0, points)
            await db.execute(
                "INSERT INTO users (tg_id, points, joined_at) VALUES (?, ?, ?)",
                (tg_id, new_pts, 0),
            )
        else:
            new_pts = max(0, row[0] + points)
            await db.execute("UPDATE users SET points = ? WHERE tg_id = ?", (new_pts, tg_id))
        await db.commit()

    verb = "增加" if action == "add" else "扣除"
    await update.message.reply_text(f"✅ 已为 ID {tg_id} {verb} {amount} 积分（当前 {new_pts}）。")

    # 回到积分页面
    context.user_data.pop("points_action", None)
    context.user_data.pop("points_tg_id", None)
    return await points_menu(update, context)


# ============================== 老师上榜管理 ==============================


async def teacher_menu(update: Update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("👭 老师上榜管理", reply_markup=teacher_kb())
    return TEACHER_MENU


async def teacher_add_start(update: Update, context):
    q = update.callback_query
    await q.answer()
    context.user_data.pop("teacher_photos", None)
    await q.edit_message_text("请输入老师姓名：")
    return TEACHER_ADD_NAME


async def teacher_add_name(update: Update, context):
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text("姓名不能为空，请重新输入：")
        return TEACHER_ADD_NAME
    context.user_data["teacher_name"] = text
    await update.message.reply_text("请输入服务地区：")
    return TEACHER_ADD_REGION


async def teacher_add_region(update: Update, context):
    context.user_data["teacher_region"] = update.message.text.strip()
    await update.message.reply_text("请输入价格档位：")
    return TEACHER_ADD_PRICE


async def teacher_add_price(update: Update, context):
    context.user_data["teacher_price"] = update.message.text.strip()
    await update.message.reply_text("请输入老师的联系方式（Telegram 用户名或链接，留空直接回车跳过）：")
    return TEACHER_ADD_CONTACT


async def teacher_add_contact(update: Update, context):
    contact = update.message.text.strip()
    context.user_data["teacher_contact"] = contact
    await update.message.reply_text(
        "请发送老师的展示照片（支持多张），\n"
        "发送完毕后请点击下方「确认上传」按钮：",
        reply_markup=teacher_photo_kb(),
    )
    return TEACHER_ADD_PHOTO


async def teacher_add_photo_collect(update: Update, context):
    """收集照片，每收到一张就在内存中追加"""
    file_id = update.message.photo[-1].file_id
    photos = context.user_data.setdefault("teacher_photos", [])
    photos.append(file_id)
    await update.message.reply_text(
        f"📸 已收到第 {len(photos)} 张照片，继续发送或点击确认上传。",
        reply_markup=teacher_photo_kb(),
    )
    return TEACHER_ADD_PHOTO


async def teacher_confirm_upload(update: Update, context):
    """确认上传 → 推送到频道 → 写入 teachers 表"""
    q = update.callback_query
    await q.answer()

    photos = context.user_data.get("teacher_photos", [])
    if not photos:
        await q.edit_message_text("请至少发送一张照片！", reply_markup=teacher_photo_kb())
        return TEACHER_ADD_PHOTO

    name = context.user_data.get("teacher_name", "")
    region = context.user_data.get("teacher_region", "")
    price = context.user_data.get("teacher_price", "")
    contact = context.user_data.get("teacher_contact", "")

    # 推送频道
    if not CHANNEL_ID:
        await q.edit_message_text(
            "❌ 频道未配置（CHANNEL_ID = 0），请先在 .env 中设置！",
            reply_markup=teacher_kb(),
        )
        return TEACHER_MENU

    caption = f"👩‍🏫 老师推荐：{name}\n📍 地区：{region}\n💰 {price}"

    try:
        media_group = [
            InputMediaPhoto(media=fid, caption=caption if i == 0 else None)
            for i, fid in enumerate(photos)
        ]
        sent = await context.bot.send_media_group(chat_id=CHANNEL_ID, media=media_group)
        first = sent[0]
        cid_str = str(CHANNEL_ID)
        if cid_str.startswith("-100"):
            cid_str = cid_str[4:]
        elif cid_str.startswith("-"):
            cid_str = cid_str[1:]
        msg_link = f"https://t.me/c/{cid_str}/{first.message_id}"
    except Exception as e:
        logger.error("频道推送失败: %s", e)
        await q.edit_message_text(
            f"❌ 频道推送失败，请确认 Bot 已是频道管理员。\n错误：{e}",
            reply_markup=teacher_kb(),
        )
        return TEACHER_MENU

    # 写数据库
    photo_ids_json = json.dumps(photos, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO teachers (name, region, price_info, photo_file_ids, channel_msg_link, contact) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, region, price, photo_ids_json, msg_link, contact),
            )
            await db.commit()
        except Exception as e:
            logger.error("老师写入 DB 失败: %s", e)
            await q.edit_message_text(
                f"❌ 数据库写入失败（姓名可能重复）：{e}",
                reply_markup=teacher_kb(),
            )
            return TEACHER_MENU

    logger.info("老师上榜成功: %s → %s", name, msg_link)
    await q.edit_message_text(
        f"✅ 老师上榜成功！\n姓名：{name}\n频道链接：{msg_link}",
        reply_markup=teacher_kb(),
    )
    return TEACHER_MENU


async def teacher_remove_list(update: Update, context):
    q = update.callback_query
    await q.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, name FROM teachers ORDER BY id",
        ) as cur:
            teachers = await cur.fetchall()

    if not teachers:
        await q.edit_message_text("暂无上榜老师。", reply_markup=teacher_kb())
        return TEACHER_MENU

    kb = [[_btn(f"❌ {t[1]}", f"admin_remove_teacher_{t[0]}")] for t in teachers]
    kb.append([_btn("🔙 返回", "admin_teacher")])
    await q.edit_message_text("请选择要下榜的老师：", reply_markup=InlineKeyboardMarkup(kb))
    return TEACHER_REMOVE_SELECT


async def teacher_remove_execute(update: Update, context):
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM teachers WHERE id = ?", (tid,))
        await db.commit()
    logger.info("管理员删除老师 ID=%d", tid)
    await q.edit_message_text("✅ 老师已下榜。", reply_markup=teacher_kb())
    return TEACHER_MENU


# ============================== 老师轮播管理 ==============================


async def _build_promote_menu_text_kb():
    """构建轮播管理菜单的文本和键盘"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, name, is_promoted FROM teachers ORDER BY id",
        ) as cur:
            teachers = await cur.fetchall()
        async with db.execute(
            "SELECT value FROM settings WHERE key = 'ad_interval_hours'",
        ) as cur:
            row = await cur.fetchone()
            interval = int(row[0]) if row else 2

    lines = ["📢 *轮播管理* — 点击老师查看详情\n"]
    kb = []
    for tid, name, promoted in teachers:
        status = "🟢" if promoted else "⚪"
        lines.append(f"{status} {name}")
        kb.append([_btn(f"{status} {name}", f"admin_show_promote_{tid}")])

    if not teachers:
        lines.append("（暂无上榜老师）")

    kb.append([_btn(f"⏱ 设置间隔（当前 {interval}h）", "admin_set_interval")])
    kb.append([_btn("🔙 返回", "admin_teacher")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


async def teacher_promote_menu(update: Update, context):
    text, kb = await _build_promote_menu_text_kb()
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        try:
            await q.edit_message_text(text, reply_markup=kb)
        except Exception:
            await q.delete_message()
            await context.bot.send_message(chat_id=q.message.chat_id, text=text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)
    return TEACHER_PROMOTE_MENU


async def teacher_promote_show(update: Update, context):
    """展示老师照片 + 轮播上架/下架"""
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    context.user_data["promote_tid"] = tid

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, region, price_info, photo_file_ids, is_promoted FROM teachers WHERE id = ?",
            (tid,),
        ) as cur:
            t = await cur.fetchone()
    if not t:
        return await teacher_promote_menu(update, context)

    name, region, price, photo_json, promoted = t
    photo_ids = json.loads(photo_json) if photo_json else []

    text = (
        f"👩‍🏫 *{name}*\n"
        f"📍 地区：{region or '未设置'}\n"
        f"💰 {price or '面议'}\n\n"
        f"轮播状态：{'🟢 已上架' if promoted else '⚪ 未上架'}"
    )
    kb = InlineKeyboardMarkup([
        [_btn("🔴 下架轮播" if promoted else "🟢 上架轮播", f"admin_toggle_promote_{tid}")],
        [_btn("🔙 返回列表", "admin_teacher_promote")],
    ])

    if photo_ids:
        await q.edit_message_media(
            InputMediaPhoto(media=photo_ids[0], caption=text),
            reply_markup=kb,
        )
    else:
        await q.edit_message_text(text, reply_markup=kb)
    return TEACHER_PROMOTE_SHOW


async def teacher_promote_toggle(update: Update, context):
    q = update.callback_query
    await q.answer()
    tid = int(q.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_promoted FROM teachers WHERE id = ?", (tid,)) as cur:
            row = await cur.fetchone()
        if row:
            new = 0 if row[0] else 1
            await db.execute("UPDATE teachers SET is_promoted = ? WHERE id = ?", (new, tid))
            await db.commit()
    # 直接刷新详情，不回调 teacher_promote_show（避免重复 answer）
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT name, region, price_info, photo_file_ids, is_promoted FROM teachers WHERE id = ?",
            (tid,),
        ) as cur:
            t = await cur.fetchone()
    name, region, price, photo_json, promoted = t
    photo_ids = json.loads(photo_json) if photo_json else []
    text = (
        f"👩‍🏫 *{name}*\n"
        f"📍 地区：{region or '未设置'}\n"
        f"💰 {price or '面议'}\n\n"
        f"轮播状态：{'🟢 已上架' if promoted else '⚪ 未上架'}"
    )
    kb = InlineKeyboardMarkup([
        [_btn("🔴 下架轮播" if promoted else "🟢 上架轮播", f"admin_toggle_promote_{tid}")],
        [_btn("🔙 返回列表", "admin_teacher_promote")],
    ])
    if photo_ids:
        await q.edit_message_media(
            InputMediaPhoto(media=photo_ids[0], caption=text), reply_markup=kb,
        )
    else:
        await q.edit_message_text(text, reply_markup=kb)
    return TEACHER_PROMOTE_SHOW


async def teacher_promote_interval(update: Update, context):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("请输入轮播间隔（小时数）：")
    return TEACHER_PROMOTE_INTERVAL


async def teacher_promote_interval_save(update: Update, context):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("请输入有效正数：")
        return TEACHER_PROMOTE_INTERVAL
    val = int(text)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('ad_interval_hours', ?)",
            (str(val),),
        )
        await db.commit()
    from utils.scheduler import reschedule_ad_interval
    reschedule_ad_interval(val)
    logger.info("轮播间隔修改为 %dh", val)
    return await teacher_promote_menu(update, context)


# ============================== 风控看板 ==============================


async def risk_dashboard(update: Update, context):
    q = update.callback_query
    await q.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1") as cur:
            banned = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(DISTINCT tg_id) FROM attendance WHERE log_date = date('now')",
        ) as cur:
            today_signed = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM invitations WHERE status = 'PENDING'",
        ) as cur:
            pending_invites = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM products WHERE is_active = 1",
        ) as cur:
            active_products = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM lotteries WHERE is_active = 1",
        ) as cur:
            active_lotteries = (await cur.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM teachers") as cur:
            total_teachers = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT value FROM settings WHERE key = 'guard_enabled'",
        ) as cur:
            row = await cur.fetchone()
            guard_on = row and row[0] == "1"
        async with db.execute("SELECT COUNT(*) FROM guard_muted") as cur:
            guard_muted_count = (await cur.fetchone())[0]

    guard_status = "✅ 已开启" if guard_on else "❌ 已关闭"
    guard_toggle_data = "admin_guard_off" if guard_on else "admin_guard_on"

    text = (
        "🛡️ *风控看板*\n\n"
        f"👥 总用户数：{total_users}\n"
        f"🚫 被封禁用户：{banned}\n"
        f"📅 今日签到：{today_signed}\n"
        f"⏳ 待处理邀请：{pending_invites}\n"
        f"🛒 上架商品：{active_products}\n"
        f"🎁 进行中抽奖：{active_lotteries}\n"
        f"👩‍🏫 上榜老师：{total_teachers}\n\n"
        f"🔒 群组校验：{guard_status}\n"
        f"🔇 被禁言用户：{guard_muted_count}"
    )
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [_btn(f"{'🔓 关闭' if guard_on else '🔒 开启'}群组校验", guard_toggle_data)],
            [_btn("📢 管理需关注的群组", "admin_channels")],
            [_btn("🔙 返回主菜单", "admin_main")],
        ]),
    )
    return MAIN_MENU


async def guard_toggle(update: Update, context):
    """开关群组校验"""
    q = update.callback_query
    await q.answer()
    new_value = "1" if q.data == "admin_guard_on" else "0"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('guard_enabled', ?)",
            (new_value,),
        )
        await db.commit()
    logger.info("群组校验 %s", "开启" if new_value == "1" else "关闭")
    # 刷新看板
    return await risk_dashboard(update, context)


# ============================== 需关注的群组管理 ==============================


async def _build_channel_list_kb():
    """构建群组列表的文本和键盘"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, chat_id, title, invite_link FROM required_channels ORDER BY id",
        ) as cur:
            channels = await cur.fetchall()
    lines = ["📢 *已配置的需关注群组：*\n"]
    kb = []
    for cid, chat_id, title_val, link_val in channels:
        lines.append(f"• {title_val} (`{chat_id}`)")
        kb.append([_btn(f"❌ {title_val}", f"admin_remove_channel_{cid}")])
    kb.append([_btn("➕ 添加群组", "admin_channel_add")])
    kb.append([_btn("🔙 返回风控", "admin_risk")])
    text = "\n".join(lines) if channels else "暂无配置的群组，请添加："
    return text, InlineKeyboardMarkup(kb)


async def required_channel_list(update: Update, context):
    """展示已配置的需关注群组列表"""
    q = update.callback_query
    await q.answer()
    text, kb = await _build_channel_list_kb()
    await q.edit_message_text(text, reply_markup=kb)
    return REQUIRED_CHANNEL_MENU


async def required_channel_add_start(update: Update, context):
    """开始添加群组：输入 chat_id"""
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "请输入群组/频道的 Chat ID（负数）：\n\n"
        "提示：可将 Bot 拉入目标群后发任意消息，用 /admin 风控看板确认"
    )
    return REQUIRED_CHANNEL_ADD_ID


async def required_channel_add_id(update: Update, context):
    """保存 chat_id，继续输入名称"""
    text = update.message.text.strip()
    if not text.lstrip("-").isdigit() or not text.startswith("-"):
        await update.message.reply_text("Chat ID 必须为负数，请重新输入：")
        return REQUIRED_CHANNEL_ADD_ID

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM required_channels WHERE chat_id = ?", (int(text),),
        ) as cur:
            if await cur.fetchone():
                text, kb = await _build_channel_list_kb()
                await update.message.reply_text("该群组已在配置列表中！", reply_markup=kb)
                return REQUIRED_CHANNEL_MENU

    context.user_data["req_chat_id"] = int(text)
    await update.message.reply_text("请输入该群组的显示名称：")
    return REQUIRED_CHANNEL_ADD_TITLE


async def required_channel_add_title(update: Update, context):
    """保存名称，继续输入邀请链接"""
    title = update.message.text.strip()
    if not title:
        await update.message.reply_text("名称不能为空，请重新输入：")
        return REQUIRED_CHANNEL_ADD_TITLE
    context.user_data["req_title"] = title
    await update.message.reply_text(
        "请输入群组邀请链接（可选，留空直接回车跳过）：\n"
        "用户未加入时会显示此链接按钮"
    )
    return REQUIRED_CHANNEL_ADD_LINK


async def required_channel_add_link(update: Update, context):
    """保存邀请链接并写入数据库"""
    link = update.message.text.strip()
    chat_id = context.user_data["req_chat_id"]
    title = context.user_data["req_title"]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO required_channels (chat_id, title, invite_link) VALUES (?, ?, ?)",
            (chat_id, title, link),
        )
        await db.commit()

    logger.info("管理员添加需关注群组: %s(%d)", title, chat_id)
    context.user_data.pop("req_chat_id", None)
    context.user_data.pop("req_title", None)

    text, kb = await _build_channel_list_kb()
    await update.message.reply_text(f"✅ 已添加！\n名称：{title}", reply_markup=kb)
    return REQUIRED_CHANNEL_MENU


async def required_channel_remove(update: Update, context):
    """删除一个需关注群组"""
    q = update.callback_query
    await q.answer()
    cid = int(q.data.split("_")[-1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM required_channels WHERE id = ?", (cid,))
        await db.commit()
    logger.info("管理员删除需关注群组 ID=%d", cid)
    text, kb = await _build_channel_list_kb()
    await q.edit_message_text(text, reply_markup=kb)
    return REQUIRED_CHANNEL_MENU


# ============================== ConversationHandler 构建 ==============================


def get_admin_conv_handler() -> ConversationHandler:
    """组装并返回管理员后台 ConversationHandler"""
    entry_filter = filters.ChatType.PRIVATE & filters.User(user_id=ADMIN_IDS)

    return ConversationHandler(
        entry_points=[CommandHandler("admin", admin_entry, filters=entry_filter)],
        states={
            # ---- 主菜单 ----
            MAIN_MENU: [
                CallbackQueryHandler(product_menu, pattern=r"^admin_product$"),
                CallbackQueryHandler(lottery_menu, pattern=r"^admin_lottery$"),
                CallbackQueryHandler(teacher_menu, pattern=r"^admin_teacher$"),
                CallbackQueryHandler(risk_dashboard, pattern=r"^admin_risk$"),
                CallbackQueryHandler(required_channel_list, pattern=r"^admin_channels$"),
                CallbackQueryHandler(guard_toggle, pattern=r"^admin_guard_(on|off)$"),
                CallbackQueryHandler(points_menu, pattern=r"^admin_points$"),
                CallbackQueryHandler(go_main, pattern=r"^admin_main$"),
            ],
            # ---- 商品管理 ----
            PRODUCT_MENU: [
                CallbackQueryHandler(product_add_start, pattern=r"^admin_product_add$"),
                CallbackQueryHandler(product_remove_list, pattern=r"^admin_product_remove$"),
                CallbackQueryHandler(product_edit_start, pattern=r"^admin_product_edit$"),
                CallbackQueryHandler(go_main, pattern=r"^admin_main$"),
            ],
            PRODUCT_ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_name),
            ],
            PRODUCT_ADD_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_desc),
            ],
            PRODUCT_ADD_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_link),
            ],
            PRODUCT_ADD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_price),
            ],
            PRODUCT_ADD_STOCK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_add_stock),
            ],
            PRODUCT_REMOVE_SELECT: [
                CallbackQueryHandler(product_remove_execute, pattern=r"^admin_remove_product_\d+$"),
                CallbackQueryHandler(product_menu, pattern=r"^admin_product$"),
            ],
            PRODUCT_EDIT_SELECT: [
                CallbackQueryHandler(product_edit_show, pattern=r"^admin_edit_product_\d+$"),
                CallbackQueryHandler(product_menu, pattern=r"^admin_product$"),
            ],
            PRODUCT_EDIT_FIELD: [
                CallbackQueryHandler(product_edit_field, pattern=r"^admin_edit_prod_\w+$"),
                CallbackQueryHandler(product_menu, pattern=r"^admin_product$"),
            ],
            PRODUCT_EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, product_edit_value),
            ],
            # ---- 抽奖管理 ----
            LOTTERY_MENU: [
                CallbackQueryHandler(lottery_add_start, pattern=r"^admin_lottery_add$"),
                CallbackQueryHandler(lottery_list, pattern=r"^admin_lottery_list$"),
                CallbackQueryHandler(lottery_toggle, pattern=r"^admin_lottery_toggle$"),
                CallbackQueryHandler(go_main, pattern=r"^admin_main$"),
            ],
            LOTTERY_ADD_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_title),
            ],
            LOTTERY_ADD_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_desc),
            ],
            LOTTERY_ADD_PRIZE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_prize),
            ],
            LOTTERY_ADD_COST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_cost),
            ],
            LOTTERY_ADD_DRAW_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_draw_time),
            ],
            LOTTERY_ADD_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_target),
            ],
            LOTTERY_ADD_MAX_PARTICIPANTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_max_participants),
            ],
            LOTTERY_ADD_WINNER_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_winner_count),
            ],
            LOTTERY_ADD_MAX_ENTRIES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_max_entries),
            ],
            LOTTERY_ADD_MIN_MSGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_add_min_msgs),
            ],
            LOTTERY_ADD_PHOTO: [
                MessageHandler(filters.PHOTO, lottery_add_photo),
                CallbackQueryHandler(lottery_skip_photo, pattern=r"^admin_lottery_skip_photo$"),
                CallbackQueryHandler(cancel, pattern=r"^admin_cancel$"),
            ],
            LOTTERY_CONFIRM: [
                CallbackQueryHandler(lottery_confirm_send, pattern=r"^admin_lottery_confirm$"),
                CallbackQueryHandler(cancel, pattern=r"^admin_cancel$"),
            ],
            # ---- 抽奖列表 / 详情 ----
            LOTTERY_DETAIL: [
                CallbackQueryHandler(lottery_detail, pattern=r"^admin_lottery_detail_\d+$"),
                CallbackQueryHandler(lottery_list, pattern=r"^admin_lottery_list$"),
                CallbackQueryHandler(lottery_menu, pattern=r"^admin_lottery$"),
                CallbackQueryHandler(go_main, pattern=r"^admin_main$"),
            ],
            LOTTERY_PARTICIPANTS: [
                CallbackQueryHandler(lottery_participants_view, pattern=r"^admin_lottery_ppl_\d+$"),
                CallbackQueryHandler(lottery_detail, pattern=r"^admin_lottery_detail_\d+$"),
                CallbackQueryHandler(lottery_remove_execute, pattern=r"^admin_remove_lottery_\d+$"),
                CallbackQueryHandler(lottery_edit_show, pattern=r"^admin_edit_lottery_\d+$"),
                CallbackQueryHandler(lottery_list, pattern=r"^admin_lottery_list$"),
                CallbackQueryHandler(lottery_menu, pattern=r"^admin_lottery$"),
                CallbackQueryHandler(go_main, pattern=r"^admin_main$"),
            ],
            LOTTERY_EDIT_FIELD: [
                CallbackQueryHandler(lottery_edit_field, pattern=r"^admin_edit_lot_\w+$"),
                CallbackQueryHandler(lottery_detail, pattern=r"^admin_lottery_detail_\d+$"),
            ],
            LOTTERY_EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lottery_edit_value),
            ],
            # ---- 老师上榜 ----
            TEACHER_MENU: [
                CallbackQueryHandler(teacher_add_start, pattern=r"^admin_teacher_add$"),
                CallbackQueryHandler(teacher_remove_list, pattern=r"^admin_teacher_remove$"),
                CallbackQueryHandler(teacher_promote_menu, pattern=r"^admin_teacher_promote$"),
                CallbackQueryHandler(go_main, pattern=r"^admin_main$"),
            ],
            TEACHER_ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_add_name),
            ],
            TEACHER_ADD_REGION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_add_region),
            ],
            TEACHER_ADD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_add_price),
            ],
            TEACHER_ADD_CONTACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_add_contact),
            ],
            TEACHER_ADD_PHOTO: [
                MessageHandler(filters.PHOTO, teacher_add_photo_collect),
                CallbackQueryHandler(teacher_confirm_upload, pattern=r"^admin_teacher_confirm$"),
                CallbackQueryHandler(teacher_menu, pattern=r"^admin_teacher$"),
            ],
            TEACHER_REMOVE_SELECT: [
                CallbackQueryHandler(teacher_remove_execute, pattern=r"^admin_remove_teacher_\d+$"),
                CallbackQueryHandler(teacher_menu, pattern=r"^admin_teacher$"),
            ],
            TEACHER_PROMOTE_MENU: [
                CallbackQueryHandler(teacher_promote_show, pattern=r"^admin_show_promote_\d+$"),
                CallbackQueryHandler(teacher_promote_interval, pattern=r"^admin_set_interval$"),
                CallbackQueryHandler(teacher_menu, pattern=r"^admin_teacher$"),
            ],
            TEACHER_PROMOTE_SHOW: [
                CallbackQueryHandler(teacher_promote_toggle, pattern=r"^admin_toggle_promote_\d+$"),
                CallbackQueryHandler(teacher_promote_menu, pattern=r"^admin_teacher_promote$"),
            ],
            TEACHER_PROMOTE_INTERVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, teacher_promote_interval_save),
            ],
            # ---- 需关注的群组管理 ----
            REQUIRED_CHANNEL_MENU: [
                CallbackQueryHandler(required_channel_add_start, pattern=r"^admin_channel_add$"),
                CallbackQueryHandler(required_channel_remove, pattern=r"^admin_remove_channel_\d+$"),
                CallbackQueryHandler(risk_dashboard, pattern=r"^admin_risk$"),
            ],
            REQUIRED_CHANNEL_ADD_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, required_channel_add_id),
            ],
            REQUIRED_CHANNEL_ADD_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, required_channel_add_title),
            ],
            REQUIRED_CHANNEL_ADD_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, required_channel_add_link),
            ],
            # ---- 积分管理 ----
            POINTS_MENU: [
                CallbackQueryHandler(points_edit_start, pattern=r"^admin_points_(add|sub)$"),
                CallbackQueryHandler(go_main, pattern=r"^admin_main$"),
            ],
            POINTS_EDIT_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, points_edit_user),
            ],
            POINTS_EDIT_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, points_edit_amount),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("admin", admin_entry, filters=entry_filter),
            CallbackQueryHandler(cancel, pattern=r"^admin_cancel$"),
        ],
    )
