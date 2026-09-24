"""All-time-low and alert-logic tests — all offline."""

from pricepulse import analysis, store


def _seed(db_path, prices):
    product_id = store.add_product(
        "Gadget", "https://example.com/g", "jsonld", db_path=db_path
    )
    for i, price in enumerate(prices):
        store.record_sample(
            product_id, price, "CAD", True,
            checked_at=f"2026-09-{i + 1:02d}T12:00:00+00:00",
            db_path=db_path,
        )
    return product_id


def test_all_time_low(tmp_path):
    db = tmp_path / "t.db"
    product_id = _seed(db, [120.0, 100.0, 110.0])
    atl = analysis.all_time_low(product_id, db_path=db)
    assert atl["price"] == 100.0


def test_all_time_low_no_samples(tmp_path):
    db = tmp_path / "t.db"
    product_id = store.add_product(
        "Gadget", "https://example.com/g", "jsonld", db_path=db
    )
    assert analysis.all_time_low(product_id, db_path=db) is None


def test_alert_on_new_atl_and_drop(tmp_path):
    db = tmp_path / "t.db"
    _seed(db, [200.0, 175.0])  # 12.5% drop and a new low
    alerts = analysis.check_alerts(db_path=db)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["product"] == "Gadget"
    assert alert["price"] == 175.0
    assert alert["at_all_time_low"] is True
    assert alert["drop_pct"] == 12.5


def test_alert_on_drop_without_new_atl(tmp_path):
    # 200 -> 170 is a 15% drop, but 100 was cheaper before, so no new ATL.
    db = tmp_path / "t.db"
    _seed(db, [100.0, 200.0, 170.0])
    alerts = analysis.check_alerts(db_path=db)
    assert len(alerts) == 1
    assert alerts[0]["at_all_time_low"] is False
    assert alerts[0]["drop_pct"] == 15.0


def test_no_alert_for_small_move(tmp_path):
    # 118 is a 1.7% dip from 120 and nowhere near the 100.0 low.
    db = tmp_path / "t.db"
    _seed(db, [100.0, 120.0, 118.0])
    assert analysis.check_alerts(db_path=db) == []


def test_no_alert_when_price_rises(tmp_path):
    db = tmp_path / "t.db"
    _seed(db, [100.0, 120.0])
    assert analysis.check_alerts(db_path=db) == []


def test_no_repeat_atl_alert_on_flat_price(tmp_path):
    db = tmp_path / "t.db"
    _seed(db, [100.0, 90.0, 90.0])  # ATL reached, then unchanged
    assert analysis.check_alerts(db_path=db) == []


def test_single_sample_has_no_baseline(tmp_path):
    db = tmp_path / "t.db"
    _seed(db, [100.0])
    assert analysis.check_alerts(db_path=db) == []


def test_custom_threshold(tmp_path):
    # 200 -> 170 is a 15% drop but not a new low (100.0 was cheaper).
    db = tmp_path / "t.db"
    _seed(db, [100.0, 200.0, 170.0])
    assert analysis.check_alerts(drop_pct=20.0, db_path=db) == []
    assert len(analysis.check_alerts(drop_pct=10.0, db_path=db)) == 1


def test_alert_carries_product_url(tmp_path):
    db = tmp_path / "t.db"
    _seed(db, [200.0, 150.0])
    alerts = analysis.check_alerts(db_path=db)
    assert alerts[0]["url"] == "https://example.com/g"
    assert alerts[0]["currency"] == "CAD"
