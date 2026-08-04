"""共用匯入管線：dry-run 隔離與逐列執行骨架。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker


@contextmanager
def dry_run_session(db: Session) -> Iterator[Session]:
    """在外層 session 自己的連線上開一個 SAVEPOINT，離開時退回。

    綁在同一條連線是刻意的：測試用 ``sqlite://`` ＋ ``StaticPool``，整個
    engine 共用一條 DBAPI 連線，另開連線會撞上「cannot start a transaction
    within a transaction」。``join_transaction_mode="create_savepoint"`` 讓
    ``BaseRepository.create()`` 內部的 ``commit()`` 只是釋放 SAVEPOINT，
    外層不受影響——所以 dry-run 走的是與真匯入完全相同的寫入路徑。
    """
    conn = db.connection()
    savepoint = conn.begin_nested()
    factory = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")
    scoped = factory()
    try:
        yield scoped
    finally:
        scoped.close()
        if savepoint.is_active:
            savepoint.rollback()
        db.expire_all()
