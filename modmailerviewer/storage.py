import asyncio
import sqlite3
import time
from contextlib import contextmanager


RETENTION = 28 * 86400


class ArchiveStore:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("CREATE TABLE IF NOT EXISTS archives (channel_id TEXT NOT NULL, message_id TEXT NOT NULL, filename TEXT NOT NULL, title TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, data BLOB NOT NULL, PRIMARY KEY(channel_id, message_id))")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    async def put(self, channel_id, message_id, filename, title, created, data):
        def write():
            with self.connect() as db:
                db.execute("DELETE FROM archives WHERE expires <= ?", (time.time(),))
                if created + RETENTION > time.time():
                    db.execute("INSERT OR REPLACE INTO archives VALUES (?, ?, ?, ?, ?, ?, ?)", (str(channel_id), str(message_id), filename, title, created, created + RETENTION, data))
        await asyncio.to_thread(write)

    async def get(self, channel_id, message_id):
        def read():
            with self.connect() as db:
                db.execute("DELETE FROM archives WHERE expires <= ?", (time.time(),))
                row = db.execute("SELECT * FROM archives WHERE channel_id=? AND message_id=?", (str(channel_id), str(message_id))).fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(read)

    async def recent(self, channel_id, limit):
        def read():
            with self.connect() as db:
                db.execute("DELETE FROM archives WHERE expires <= ?", (time.time(),))
                rows = db.execute("SELECT channel_id,message_id,filename,title,created,expires FROM archives WHERE channel_id=? ORDER BY created DESC LIMIT ?", (str(channel_id), limit)).fetchall()
                return [dict(row) for row in rows]
        return await asyncio.to_thread(read)

    async def expire(self):
        def remove():
            with self.connect() as db:
                db.execute("DELETE FROM archives WHERE expires <= ?", (time.time(),))
                db.execute("PRAGMA secure_delete=ON")
        await asyncio.to_thread(remove)
