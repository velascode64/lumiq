from __future__ import annotations

from pathlib import Path

from lumiq.platform.db.core import DatabaseManager, sa, watchlist_groups
from lumiq.platform.db.repositories import DbWatchlistRepository


def test_watchlist_repo_persists_watchlist_groups_rows(tmp_path: Path):
    db_path = tmp_path / "watchlist.db"
    manager = DatabaseManager(db_url=f"sqlite+pysqlite:///{db_path}", auto_create=True, echo=False)
    repo = DbWatchlistRepository(manager)

    repo.upsert_ticker("GOOG", ["faang"], favorite=False)
    repo.upsert_ticker("QQQ", ["faang"], favorite=False)
    repo.upsert_ticker("META", ["faang"], favorite=True)

    cfg = repo.load_config_dict()
    assert "faang" in cfg["groups"]
    assert set(cfg["groups"]["faang"]) == {"GOOG", "QQQ", "META"}
    assert "META" in cfg["favorites"]

    removed = repo.remove_ticker("QQQ", group_name="faang")
    assert "faang" in removed["removed_from_groups"]

    cfg2 = repo.load_config_dict()
    assert set(cfg2["groups"]["faang"]) == {"GOOG", "META"}

    rg = repo.remove_group("faang")
    assert rg["removed_group"] is True

    cfg3 = repo.load_config_dict()
    assert "faang" not in cfg3["groups"]

    with manager.connect() as conn:
        rows = conn.execute(sa.select(watchlist_groups).order_by(watchlist_groups.c.name.asc())).mappings().all()
    assert len(rows) == 1
    assert rows[0]["name"] == "favorites"
    assert rows[0]["kind"] == "favorites"
    assert rows[0]["tickers"] == ["META"]
