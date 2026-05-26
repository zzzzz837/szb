import aiosqlite
from telegram import Message
from telegram.ext.filters import MessageFilter

from config import DB_PATH, MAIN_GROUP_ID, ADMIN_IDS

# 附属群 ID 内存缓存，通过 refresh_slave_groups() 从 registered_chats 加载
_SLAVE_IDS: set[int] = set()


async def refresh_slave_groups() -> None:
    """从 DB 刷新附属群 ID 列表（启动时 / 有新群注册时调用）"""
    global _SLAVE_IDS
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT chat_id FROM registered_chats WHERE chat_type = 'SLAVE'",
        ) as cur:
            _SLAVE_IDS = {row[0] for row in await cur.fetchall()}


class _MainGroup(MessageFilter):
    """仅匹配主群消息"""
    def filter(self, message: Message) -> bool:
        return message.chat_id == MAIN_GROUP_ID


class _SlaveGroup(MessageFilter):
    """仅匹配附属群消息（查内存缓存，兜底用 chat_id 判断）"""
    def filter(self, message: Message) -> bool:
        if _SLAVE_IDS:
            return message.chat_id in _SLAVE_IDS
        return message.chat_id != MAIN_GROUP_ID and message.chat_id < 0


class _IsAdmin(MessageFilter):
    """用户是否为配置的管理员（不限私聊或群聊）"""
    def filter(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS


# 单例导出
main_group = _MainGroup()
slave_group = _SlaveGroup()
is_admin = _IsAdmin()
