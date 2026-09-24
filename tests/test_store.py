"""SQLite storage round-trip tests — all offline."""

import pytest

from pricepulse import store


def test_add_and_get(tmp_path):
    db = tmp_path / "t.db"
    product_id = store.add_product(
        "Widget", "https://example.com/w", "jsonld", db_path=db
    )
    product = store.get_product("Widget", db_path=db)
    assert product["id"] == product_id
    assert product["url"] == "https://example.com/w"
    assert product["provider"] == "jsonld"


def test_get_missing_returns_none(tmp_path):
    assert store.get_product("Nope", db_path=tmp_path / "t.db") is None


def test_add_duplicate_name_raises(tmp_path):
    db = tmp_path / "t.db"
    store.add_product("Widget", "https://example.com/w", "jsonld", db_path=db)
    with pytest.raises(ValueError, match="already tracked"):
        store.add_product("Widget", "https://example.com/w2", "jsonld", db_path=db)


def test_list_products_sorted(tmp_path):
    db = tmp_path / "t.db"
    store.add_product("Zebra", "https://example.com/z", "jsonld", db_path=db)
    store.add_product("Apple", "https://example.com/a", "jsonld", db_path=db)
    names = [p["name"] for p in store.list_products(db_path=db)]
    assert names == ["Apple", "Zebra"]


def test_record_sample_and_history_order(tmp_path):
    db = tmp_path / "t.db"
    product_id = store.add_product(
        "Widget", "https://example.com/w", "jsonld", db_path=db
    )
    store.record_sample(
        product_id, 100.0, "CAD", True,
        checked_at="2026-09-01T12:00:00+00:00", db_path=db,
    )
    store.record_sample(
        product_id, 90.0, "CAD", False,
        checked_at="2026-09-02T12:00:00+00:00", db_path=db,
    )
    history = store.history(product_id, db_path=db)
    assert [s["price"] for s in history] == [100.0, 90.0]
    assert [s["in_stock"] for s in history] == [1, 0]
    assert history[0]["currency"] == "CAD"


def test_history_empty_for_new_product(tmp_path):
    db = tmp_path / "t.db"
    product_id = store.add_product(
        "Widget", "https://example.com/w", "jsonld", db_path=db
    )
    assert store.history(product_id, db_path=db) == []
