"""Local web dashboard for pricepulse (stdlib only).

Serves a single-page dashboard plus a small JSON API:

    GET  /                  the dashboard (pricepulse/static/index.html)
    GET  /api/products      every tracked product with latest price, ATL and history
    GET  /api/alerts        current alerts from analysis.check_alerts()
    POST /api/add           {"name", "url"} — track a new product
    POST /api/record        {"name", "price", "currency"?, "out_of_stock"?}
    POST /api/check         fetch all products, return {"alerts", "errors"}

Errors are returned as clean JSON ({"error": ...}) with a proper status
code — never a traceback.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import analysis, providers, store

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _provider_by_name(name: str) -> providers.Provider:
    for provider in providers.PROVIDERS:
        if provider.name == name:
            return provider
    return providers.ManualProvider()


def product_payload(product: dict, db_path=None) -> dict:
    """Shape one product for GET /api/products."""
    samples = store.history(product["id"], db_path=db_path)
    latest = samples[-1] if samples else None
    atl_row = (
        analysis.all_time_low(product["id"], db_path=db_path) if samples else None
    )
    atl_price = float(atl_row["price"]) if atl_row else None
    latest_price = float(latest["price"]) if latest else None
    return {
        "id": product["id"],
        "name": product["name"],
        "url": product["url"],
        "provider": product["provider"],
        "latest": (
            {
                "price": latest_price,
                "currency": latest["currency"],
                "in_stock": bool(latest["in_stock"]),
                "checked_at": latest["checked_at"],
            }
            if latest
            else None
        ),
        "atl": atl_price,
        "is_atl": bool(
            latest_price is not None
            and atl_price is not None
            and latest_price == atl_price
        ),
        "history": [
            {"price": float(s["price"]), "checked_at": s["checked_at"]}
            for s in samples
        ],
    }


def run_check(db_path=None, drop_pct: float = 10.0) -> dict:
    """Fetch every tracked product, mirroring `pricepulse check`.

    Per-product fetch failures are collected into ``errors`` and never
    crash the run; manual-provider products are skipped gracefully.
    """
    errors: list[dict] = []
    for product in store.list_products(db_path=db_path):
        provider = _provider_by_name(product["provider"])
        if isinstance(provider, providers.ManualProvider):
            continue
        try:
            sample = provider.fetch(product["url"])
        except Exception as exc:  # noqa: BLE001 - report per product, keep going
            errors.append({"product": product["name"], "error": str(exc)})
            continue
        store.record_sample(
            product["id"],
            sample.price,
            sample.currency,
            sample.in_stock,
            db_path=db_path,
        )
    return {
        "alerts": analysis.check_alerts(drop_pct=drop_pct, db_path=db_path),
        "errors": errors,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "pricepulse-dashboard"

    # -- helpers ---------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # noqa: D102
        pass  # stay quiet; this is a local dashboard, not a log firehose

    def _db(self):
        return self.server.db_path  # type: ignore[attr-defined]

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return "INVALID"
        if length <= 0 or length > 1_000_000:
            return "INVALID" if length else None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return "INVALID"

    def _serve_index(self) -> None:
        page = STATIC_DIR / "index.html"
        if not page.exists():
            self._send_json({"error": "dashboard page not found"}, status=500)
            return
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        db = self._db()
        if path == "/":
            self._serve_index()
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif path == "/api/products":
            products = [
                product_payload(p, db_path=db)
                for p in store.list_products(db_path=db)
            ]
            self._send_json(products)
        elif path == "/api/alerts":
            self._send_json({"alerts": analysis.check_alerts(db_path=db)})
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/add":
            self._handle_add()
        elif path == "/api/record":
            self._handle_record()
        elif path == "/api/check":
            self._handle_check()
        else:
            self._send_json({"error": "not found"}, status=404)

    # -- POST handlers ---------------------------------------------------
    def _handle_add(self) -> None:
        data = self._read_json()
        if data == "INVALID" or not isinstance(data, dict):
            self._send_json({"error": "expected a JSON object"}, status=400)
            return
        name = (data.get("name") or "").strip()
        url = (data.get("url") or "").strip()
        if not name or not url:
            self._send_json(
                {"error": "both 'name' and 'url' are required"}, status=400
            )
            return
        provider = providers.resolve_provider(url)
        try:
            product_id = store.add_product(
                name, url, provider.name, db_path=self._db()
            )
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=409)
            return
        self._send_json(
            {"id": product_id, "name": name, "provider": provider.name}, status=201
        )

    def _handle_record(self) -> None:
        data = self._read_json()
        if data == "INVALID" or not isinstance(data, dict):
            self._send_json({"error": "expected a JSON object"}, status=400)
            return
        name = (data.get("name") or "").strip()
        if not name:
            self._send_json({"error": "'name' is required"}, status=400)
            return
        try:
            price = float(data.get("price"))
        except (TypeError, ValueError):
            self._send_json(
                {"error": "'price' must be a number"}, status=400
            )
            return
        if price <= 0:
            self._send_json({"error": "'price' must be positive"}, status=400)
            return
        currency = str(data.get("currency") or "CAD").upper()
        product = store.get_product(name, db_path=self._db())
        if product is None:
            self._send_json({"error": f"no product named {name!r}"}, status=404)
            return
        store.record_sample(
            product["id"],
            price,
            currency,
            not bool(data.get("out_of_stock")),
            db_path=self._db(),
        )
        self._send_json(
            {"ok": True, "name": name, "price": price, "currency": currency},
            status=201,
        )

    def _handle_check(self) -> None:
        # Drain any body so the connection stays reusable; payload unused.
        self._read_json()
        try:
            result = run_check(
                db_path=self._db(), drop_pct=self.server.drop_pct  # type: ignore[attr-defined]
            )
        except Exception as exc:  # noqa: BLE001 - never leak a traceback
            self._send_json({"error": f"check failed: {exc}"}, status=500)
            return
        self._send_json(result)


class DashboardServer(ThreadingHTTPServer):
    """HTTP server carrying the dashboard's config (db path, alert tuning)."""

    daemon_threads = True

    def __init__(self, address, db_path=None, drop_pct: float = 10.0):
        self.db_path = db_path
        self.drop_pct = drop_pct
        super().__init__(address, DashboardHandler)


def make_server(
    port: int = 8000, db_path=None, drop_pct: float = 10.0
) -> DashboardServer:
    """Build (but don't start) a dashboard server. Port 0 = ephemeral."""
    return DashboardServer(("127.0.0.1", port), db_path=db_path, drop_pct=drop_pct)


def serve(port: int = 8000, db_path=None, drop_pct: float = 10.0) -> int:
    """Start the dashboard and block until Ctrl-C."""
    server = make_server(port, db_path=db_path, drop_pct=drop_pct)
    _, real_port = server.server_address
    url = f"http://127.0.0.1:{real_port}"
    print(f"pricepulse dashboard running at {url}")
    print("press Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    serve()
