"""CLI tests — all offline (no `check` against live sites here)."""

import sys
from argparse import Namespace

from pricepulse import cli, store


def _ns(**kwargs):
    return Namespace(**kwargs)


def test_add_then_record_then_history_and_atl(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    assert cli.cmd_add(_ns(name="Gadget", url="https://example.com/g", db=db)) == 0
    product = store.get_product("Gadget", db_path=db)
    assert product["provider"] == "jsonld"

    assert (
        cli.cmd_record(
            _ns(name="Gadget", price=99.99, currency="CAD",
                out_of_stock=False, db=db)
        )
        == 0
    )
    assert (
        cli.cmd_record(
            _ns(name="Gadget", price=89.99, currency="CAD",
                out_of_stock=False, db=db)
        )
        == 0
    )

    assert cli.cmd_history(_ns(name="Gadget", db=db)) == 0
    assert "89.99" in capsys.readouterr().out

    assert cli.cmd_atl(_ns(name="Gadget", db=db)) == 0
    out = capsys.readouterr().out
    assert "89.99" in out
    assert "all-time low" in out


def test_add_costco_url_selects_manual_provider(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    assert (
        cli.cmd_add(
            _ns(name="S26 FE", url="https://www.costco.ca/p/galaxy-s26-fe/123", db=db)
        )
        == 0
    )
    product = store.get_product("S26 FE", db_path=db)
    assert product["provider"] == "manual"
    assert "pricepulse record" in capsys.readouterr().out


def test_add_duplicate_fails(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    cli.cmd_add(_ns(name="Gadget", url="https://example.com/g", db=db))
    assert cli.cmd_add(_ns(name="Gadget", url="https://example.com/g2", db=db)) == 1
    assert "already tracked" in capsys.readouterr().err


def test_commands_reject_unknown_product(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    assert cli.cmd_history(_ns(name="Ghost", db=db)) == 1
    assert cli.cmd_atl(_ns(name="Ghost", db=db)) == 1
    assert (
        cli.cmd_record(
            _ns(name="Ghost", price=1.0, currency="CAD", out_of_stock=False, db=db)
        )
        == 1
    )
    assert "no product named" in capsys.readouterr().err


def test_check_with_no_products(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    assert cli.cmd_check(_ns(db=db, drop_pct=10.0)) == 0
    assert "nothing tracked" in capsys.readouterr().out


def test_check_skips_manual_products(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    cli.cmd_add(
        _ns(name="S26 FE", url="https://www.costco.ca/p/galaxy-s26-fe/123", db=db)
    )
    capsys.readouterr()  # drain the add output
    assert cli.cmd_check(_ns(db=db, drop_pct=10.0)) == 0
    out = capsys.readouterr().out
    assert "manual provider" in out
    assert "no alerts." in out


def test_record_out_of_stock_flag(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    cli.cmd_add(_ns(name="Gadget", url="https://example.com/g", db=db))
    product = store.get_product("Gadget", db_path=db)
    cli.cmd_record(
        _ns(name="Gadget", price=50.0, currency="CAD", out_of_stock=True, db=db)
    )
    history = store.history(product["id"], db_path=db)
    assert history[0]["in_stock"] == 0
    assert "out of stock" in capsys.readouterr().out


def test_main_argv_add(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "t.db")
    monkeypatch.setattr(
        sys, "argv", ["pricepulse", "--db", db, "add", "Gadget", "https://example.com/g"]
    )
    assert cli.main() == 0
    assert store.get_product("Gadget", db_path=db) is not None
    assert "tracking" in capsys.readouterr().out


def test_main_argv_record_and_atl(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "t.db")
    monkeypatch.setattr(
        sys, "argv", ["pricepulse", "--db", db, "add", "Gadget", "https://example.com/g"]
    )
    cli.main()
    monkeypatch.setattr(
        sys, "argv", ["pricepulse", "--db", db, "record", "Gadget", "42.50"]
    )
    assert cli.main() == 0
    monkeypatch.setattr(sys, "argv", ["pricepulse", "--db", db, "atl", "Gadget"])
    assert cli.main() == 0
    assert "42.50" in capsys.readouterr().out
