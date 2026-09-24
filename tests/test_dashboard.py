"""Dashboard tests — a live server on an ephemeral port, everything offline."""

import json
import sys
import threading
import urllib.error
import urllib.request

import pytest

from pricepulse import dashboard


@pytest.fixture()
def server(tmp_path):
    db = str(tmp_path / "dash.db")
    srv = dashboard.make_server(0, db_path=db)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    thread.join(timeout=10)
    srv.server_close()


def _call(server, method, path, payload=None, raw_body=None):
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    if raw_body is not None:
        data = raw_body
    elif payload is not None:
        data = json.dumps(payload).encode("utf-8")
    else:
        data = None
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json(server, method, path, payload=None, raw_body=None):
    status, body = _call(server, method, path, payload, raw_body)
    return status, json.loads(body.decode("utf-8"))


def test_index_served(server):
    status, body = _call(server, "GET", "/")
    assert status == 200
    assert b"pricepulse" in body
    assert b"<svg" in body or b"sparkline" in body


def test_add_record_then_payload_atl_and_is_atl(server):
    status, data = _json(
        server, "POST", "/api/add",
        {"name": "Gadget", "url": "https://example.com/g"},
    )
    assert status == 201
    assert data["name"] == "Gadget"
    assert data["provider"] == "jsonld"

    assert _json(server, "POST", "/api/record",
                 {"name": "Gadget", "price": 99.99})[0] == 201
    assert _json(server, "POST", "/api/record",
                 {"name": "Gadget", "price": 89.99})[0] == 201

    status, products = _json(server, "GET", "/api/products")
    assert status == 200
    assert isinstance(products, list) and len(products) == 1
    p = products[0]
    assert p["name"] == "Gadget"
    assert p["url"] == "https://example.com/g"
    assert p["provider"] == "jsonld"
    assert p["latest"]["price"] == 89.99
    assert p["latest"]["currency"] == "CAD"
    assert p["latest"]["in_stock"] is True
    assert p["latest"]["checked_at"]
    assert p["atl"] == 89.99
    assert p["is_atl"] is True
    assert [s["price"] for s in p["history"]] == [99.99, 89.99]


def test_is_atl_false_when_price_rises_again(server):
    _json(server, "POST", "/api/add", {"name": "Gadget", "url": "https://example.com/g"})
    _json(server, "POST", "/api/record", {"name": "Gadget", "price": 89.99})
    _json(server, "POST", "/api/record", {"name": "Gadget", "price": 99.99})

    _, products = _json(server, "GET", "/api/products")
    p = products[0]
    assert p["latest"]["price"] == 99.99
    assert p["atl"] == 89.99
    assert p["is_atl"] is False


def test_alerts_endpoint_shape(server):
    _json(server, "POST", "/api/add", {"name": "Gadget", "url": "https://example.com/g"})
    _json(server, "POST", "/api/record", {"name": "Gadget", "price": 99.99})
    _json(server, "POST", "/api/record", {"name": "Gadget", "price": 89.99})

    status, data = _json(server, "GET", "/api/alerts")
    assert status == 200
    assert isinstance(data["alerts"], list)
    assert len(data["alerts"]) == 1
    alert = data["alerts"][0]
    assert alert["product"] == "Gadget"
    assert alert["price"] == 89.99
    assert alert["currency"] == "CAD"
    assert alert["previous_price"] == 99.99
    assert alert["at_all_time_low"] is True


def test_check_skips_manual_and_returns_shape(server):
    # costco.ca auto-resolves to the manual provider: nothing to fetch,
    # so the check must succeed with zero errors.
    _json(server, "POST", "/api/add",
          {"name": "S26 FE", "url": "https://www.costco.ca/p/galaxy-s26-fe/123"})
    status, data = _json(server, "POST", "/api/check")
    assert status == 200
    assert data["alerts"] == []
    assert data["errors"] == []


def test_clean_json_errors_never_tracebacks(server):
    # duplicate add
    _json(server, "POST", "/api/add", {"name": "Gadget", "url": "https://example.com/g"})
    status, data = _json(
        server, "POST", "/api/add", {"name": "Gadget", "url": "https://example.com/g2"}
    )
    assert status == 409
    assert "error" in data
    assert "Traceback" not in json.dumps(data)

    # missing fields
    status, data = _json(server, "POST", "/api/add", {"name": "NoURL"})
    assert status == 400 and "error" in data

    # invalid JSON body
    status, body = _call(server, "POST", "/api/add", raw_body=b"{nope")
    assert status == 400
    assert b"Traceback" not in body
    assert b"error" in body

    # unknown product
    status, data = _json(
        server, "POST", "/api/record", {"name": "Ghost", "price": 10.0}
    )
    assert status == 404 and "error" in data

    # bad price
    status, data = _json(
        server, "POST", "/api/record", {"name": "Gadget", "price": "free"}
    )
    assert status == 400 and "error" in data

    # unknown route
    status, data = _json(server, "GET", "/api/nope")
    assert status == 404 and "error" in data


def test_record_out_of_stock_flag(server):
    _json(server, "POST", "/api/add", {"name": "Gadget", "url": "https://example.com/g"})
    status, data = _json(
        server, "POST", "/api/record",
        {"name": "Gadget", "price": 50.0, "out_of_stock": True},
    )
    assert status == 201
    _, products = _json(server, "GET", "/api/products")
    assert products[0]["latest"]["in_stock"] is False


def test_dashboard_cli_wiring(tmp_path, monkeypatch, capsys):
    # The `dashboard` subcommand exists and prints the URL; stop the
    # server immediately by making serve_forever raise KeyboardInterrupt.
    from pricepulse import cli

    db = str(tmp_path / "t.db")
    real_server = dashboard.DashboardServer

    class QuickStop(real_server):
        def serve_forever(self, *a, **k):
            raise KeyboardInterrupt

    monkeypatch.setattr(dashboard, "DashboardServer", QuickStop)
    monkeypatch.setattr(
        sys, "argv",
        ["pricepulse", "--db", db, "dashboard", "--port", "0"],
    )
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "http://127.0.0.1:" in out
