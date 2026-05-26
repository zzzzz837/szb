import aiosqlite

from config import DB_PATH


async def init_db():
    """初始化数据库，创建所有核心业务表"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                points INTEGER DEFAULT 0,
                last_chat_time INTEGER DEFAULT 0,
                joined_at INTEGER,
                is_banned INTEGER DEFAULT 0,
                total_msgs INTEGER DEFAULT 0
            )
        """)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN total_msgs INTEGER DEFAULT 0")
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS registered_chats (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT,
                chat_type TEXT DEFAULT 'SLAVE'
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                tg_id INTEGER,
                log_date TEXT,
                streak_days INTEGER DEFAULT 1,
                PRIMARY KEY (tg_id, log_date)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER,
                invitee_id INTEGER UNIQUE,
                status TEXT DEFAULT 'PENDING',
                created_at INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                content_link TEXT,
                price INTEGER,
                stock INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS lotteries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                prize TEXT,
                cost_points INTEGER,
                draw_time INTEGER,
                target_winner_id INTEGER DEFAULT 0,
                max_participants INTEGER DEFAULT 0,
                winner_count INTEGER DEFAULT 1,
                max_entries_per_user INTEGER DEFAULT 1,
                min_msgs INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)
        for col, default in (("max_participants", 0), ("winner_count", 1), ("max_entries_per_user", 1), ("min_msgs", 0)):
            try:
                await db.execute(f"ALTER TABLE lotteries ADD COLUMN {col} INTEGER DEFAULT {default}")
            except Exception:
                pass
        try:
            await db.execute("ALTER TABLE lotteries ADD COLUMN photo_file_id TEXT DEFAULT ''")
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS lottery_participants (
                lottery_id INTEGER,
                tg_id INTEGER,
                entries INTEGER DEFAULT 1,
                PRIMARY KEY (lottery_id, tg_id)
            )
        """)
        try:
            await db.execute("ALTER TABLE lottery_participants ADD COLUMN entries INTEGER DEFAULT 1")
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE,
                title TEXT,
                invite_link TEXT DEFAULT ''
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # 默认开启群组校验 和 抽奖功能
        for k, v in (('guard_enabled', '1'), ('lottery_enabled', '1')):
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )

        await db.execute("""
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                region TEXT,
                price_info TEXT,
                photo_file_ids TEXT,
                channel_msg_link TEXT,
                contact TEXT DEFAULT '',
                is_promoted INTEGER DEFAULT 0
            )
        """)

        # 兼容旧表：新增 contact 字段（已有表则忽略）
        try:
            await db.execute("ALTER TABLE teachers ADD COLUMN contact TEXT DEFAULT ''")
        except Exception:
            pass

        # 群组校验禁言表（记录被禁言用户，用于定时检查后自动解禁）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS guard_muted (
                tg_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                muted_at INTEGER NOT NULL,
                PRIMARY KEY (tg_id, chat_id)
            )
        """)

        # 群成员独立数据表（用于每个群独立的排行和积分）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                tg_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                points INTEGER DEFAULT 0,
                total_msgs INTEGER DEFAULT 0,
                last_chat_time INTEGER DEFAULT 0,
                joined_at INTEGER DEFAULT 0,
                PRIMARY KEY (tg_id, chat_id)
            )
        """)

        # 入群验证码
        await db.execute("""
            CREATE TABLE IF NOT EXISTS join_verify (
                tg_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)

        await db.commit()


async def update_user_points(tg_id: int, points: int, username: str = None):
    """安全增减用户积分"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT points FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO users (tg_id, username, points, joined_at) VALUES (?, ?, ?, ?)",
                (tg_id, username, points, 0),
            )
        else:
            new_points = max(0, row[0] + points)
            await db.execute(
                "UPDATE users SET points = ?, username = ? WHERE tg_id = ?",
                (new_points, username, tg_id),
            )
        await db.commit()


async def get_user_points(tg_id: int) -> int:
    """获取用户当前积分"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT points FROM users WHERE tg_id = ?", (tg_id,)) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0
