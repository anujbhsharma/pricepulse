"""Command-line interface for pricepulse.

Subcommands:
    add       track a new product by name and URL
    check     fetch every tracked product, store samples, print alerts
    history   show the recorded price history for a product
    atl       show the all-time low for a product
    record    manually log a price (for bot-walled stores like Costco)
    dashboard start a local web dashboard to browse everything
"""

from __future__ import annotations

import argparse
import sys

from . import analysis, providers, store


def _provider_by_name(name: str) -> providers.Provider:
    for provider in providers.PROVIDERS:
        if provider.name == name:
            return provider
    return providers.ManualProvider()


def _format_alert(alert: dict) -> str:
    lines = [f"ALERT: {alert['product']} — {alert['price']:.2f} {alert['currency']}"]
    if alert["at_all_time_low"]:
        lines.append("  * new all-time low")
    if alert["drop_pct"] > 0:
        lines.append(
            f"  * down {alert['drop_pct']}% from {alert['previous_price']:.2f}"
        )
    lines.append(f"  {alert['url']}")
    return "\n".join(lines)


def cmd_add(args: argparse.Namespace) -> int:
    provider = providers.resolve_provider(args.url)
    try:
        product_id = store.add_product(
            args.name, args.url, provider.name, db_path=args.db
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"tracking {args.name!r} (id {product_id}) via provider {provider.name!r}")
    if isinstance(provider, providers.ManualProvider):
        print("hint: this store is bot-walled — log prices by hand:")
        print(f"  pricepulse record {args.name!r} <price>")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    products = store.list_products(db_path=args.db)
    if not products:
        print("nothing tracked yet — add one with `pricepulse add <name> <url>`")
        return 0
    for product in products:
        provider = _provider_by_name(product["provider"])
        if isinstance(provider, providers.ManualProvider):
            print(f"skip {product['name']!r}: manual provider, use `pricepulse record`")
            continue
        try:
            sample = provider.fetch(product["url"])
        except Exception as exc:  # noqa: BLE001 - report per product, keep going
            print(f"error fetching {product['name']!r}: {exc}", file=sys.stderr)
            continue
        store.record_sample(
            product["id"],
            sample.price,
            sample.currency,
            sample.in_stock,
            db_path=args.db,
        )
        stock = "in stock" if sample.in_stock else "out of stock"
        print(f"{product['name']}: {sample.price:.2f} {sample.currency} ({stock})")
    alerts = analysis.check_alerts(drop_pct=args.drop_pct, db_path=args.db)
    if alerts:
        print()
        for alert in alerts:
            print(_format_alert(alert))
            print()
    else:
        print("no alerts.")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    product = store.get_product(args.name, db_path=args.db)
    if product is None:
        print(f"error: no product named {args.name!r}", file=sys.stderr)
        return 1
    samples = store.history(product["id"], db_path=args.db)
    if not samples:
        print(f"no samples for {args.name!r} yet — run `pricepulse check`")
        return 0
    print(f"{'checked_at':<28}{'price':>12}  stock")
    for sample in samples:
        stock = "yes" if sample["in_stock"] else "no"
        print(
            f"{sample['checked_at']:<28}{sample['price']:>12.2f}"
            f"  {stock}  {sample['currency']}"
        )
    return 0


def cmd_atl(args: argparse.Namespace) -> int:
    product = store.get_product(args.name, db_path=args.db)
    if product is None:
        print(f"error: no product named {args.name!r}", file=sys.stderr)
        return 1
    atl = analysis.all_time_low(product["id"], db_path=args.db)
    if atl is None:
        print(f"no samples for {args.name!r} yet — run `pricepulse check`")
        return 0
    print(
        f"all-time low for {args.name!r}: {atl['price']:.2f} {atl['currency']}"
        f" (seen {atl['checked_at']})"
    )
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    product = store.get_product(args.name, db_path=args.db)
    if product is None:
        print(f"error: no product named {args.name!r}", file=sys.stderr)
        return 1
    store.record_sample(
        product["id"],
        args.price,
        args.currency,
        not args.out_of_stock,
        db_path=args.db,
    )
    stock = "out of stock" if args.out_of_stock else "in stock"
    print(f"recorded {args.price:.2f} {args.currency} for {args.name!r} ({stock})")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    from . import dashboard

    return dashboard.serve(port=args.port, db_path=args.db)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pricepulse", description="Track gadget prices across Canadian retailers."
    )
    parser.add_argument(
        "--db",
        default=None,
        help="path to SQLite database (default: ~/.pricepulse/prices.db)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="track a new product")
    p_add.add_argument("name", help="friendly name, e.g. 'Anker 25K power bank'")
    p_add.add_argument("url", help="product page URL")
    p_add.set_defaults(func=cmd_add)

    p_check = sub.add_parser("check", help="fetch all products and print alerts")
    p_check.add_argument(
        "--drop-pct",
        type=float,
        default=10.0,
        help="alert when a price drops by at least this percent (default: 10)",
    )
    p_check.set_defaults(func=cmd_check)

    p_history = sub.add_parser("history", help="show recorded price history")
    p_history.add_argument("name", help="product name as given to `add`")
    p_history.set_defaults(func=cmd_history)

    p_atl = sub.add_parser("atl", help="show the all-time low price")
    p_atl.add_argument("name", help="product name as given to `add`")
    p_atl.set_defaults(func=cmd_atl)

    p_record = sub.add_parser("record", help="manually log a price")
    p_record.add_argument("name", help="product name as given to `add`")
    p_record.add_argument("price", type=float, help="observed price")
    p_record.add_argument("--currency", default="CAD", help="currency code (default: CAD)")
    p_record.add_argument(
        "--out-of-stock", action="store_true", help="mark the item out of stock"
    )
    p_record.set_defaults(func=cmd_record)

    p_dash = sub.add_parser(
        "dashboard", help="start a local web dashboard in your browser"
    )
    p_dash.add_argument(
        "--port", type=int, default=8000, help="port to listen on (default: 8000)"
    )
    p_dash.set_defaults(func=cmd_dashboard)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
