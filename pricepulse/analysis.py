"""All-time-low detection and price-drop alerts over stored samples."""

from __future__ import annotations

from . import store


def all_time_low(product_id: int, db_path=None) -> dict | None:
    """The cheapest sample ever recorded for a product, or None."""
    samples = store.history(product_id, db_path=db_path)
    if not samples:
        return None
    return min(samples, key=lambda s: s["price"])


def check_alerts(drop_pct: float = 10.0, db_path=None) -> list[dict]:
    """Find products worth shouting about.

    One alert per product, emitted when the latest sample is a *new*
    all-time low (strictly cheaper than every previous sample, so a flat
    price at the low doesn't re-alert every run) or when it dropped by at
    least ``drop_pct`` since the previous check. Products with fewer than
    two samples have no baseline and are skipped.
    """
    alerts = []
    for product in store.list_products(db_path=db_path):
        samples = store.history(product["id"], db_path=db_path)
        if len(samples) < 2:
            continue
        *previous, latest = samples
        prev_price = previous[-1]["price"]
        latest_price = latest["price"]
        prev_atl = min(s["price"] for s in previous)
        new_atl = latest_price < prev_atl
        drop = (
            (prev_price - latest_price) / prev_price * 100 if prev_price > 0 else 0.0
        )
        if new_atl or drop >= drop_pct:
            alerts.append(
                {
                    "product": product["name"],
                    "url": product["url"],
                    "price": latest_price,
                    "currency": latest["currency"],
                    "previous_price": prev_price,
                    "drop_pct": round(drop, 1),
                    "at_all_time_low": new_atl,
                }
            )
    return alerts
