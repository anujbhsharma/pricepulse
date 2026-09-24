"""Provider parsing tests — all offline, against saved HTML fixtures."""

from pathlib import Path

import pytest

from pricepulse import providers

FIXTURES = Path(__file__).parent / "fixtures"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_jsonld_single_offer():
    sample = providers.JsonLdProvider().parse(_html("bestbuy_product.html"))
    assert sample.price == 129.18
    assert sample.currency == "CAD"
    assert sample.in_stock is True


def test_jsonld_graph_style_offer():
    sample = providers.JsonLdProvider().parse(_html("walmart_product.html"))
    assert sample.price == 949.99
    assert sample.currency == "CAD"
    assert sample.in_stock is True


def test_jsonld_out_of_stock_flag():
    sample = providers.JsonLdProvider().parse(_html("generic_outofstock.html"))
    assert sample.price == 109.99
    assert sample.in_stock is False


def test_jsonld_multi_offer_picks_lowest_in_stock():
    # 899.99 is cheaper but out of stock, so 949.99 wins.
    sample = providers.JsonLdProvider().parse(_html("multi_offer.html"))
    assert sample.price == 949.99
    assert sample.in_stock is True


def test_jsonld_no_offer_raises():
    with pytest.raises(ValueError, match="no priced Offer"):
        providers.JsonLdProvider().parse("<html><body>nothing here</body></html>")


def test_jsonld_broken_script_block_is_skipped():
    html = (
        '<script type="application/ld+json">{not valid json</script>'
        '<script type="application/ld+json">'
        '{"@type":"Offer","price":"10.00","priceCurrency":"CAD",'
        '"availability":"https://schema.org/InStock"}</script>'
    )
    sample = providers.JsonLdProvider().parse(html)
    assert sample.price == 10.00


def test_matches():
    assert providers.BestBuyCAProvider().matches(
        "https://www.bestbuy.ca/en-ca/product/anker-laptop-power-bank/19988724"
    )
    assert not providers.BestBuyCAProvider().matches(
        "https://www.walmart.ca/en/ip/widget/123"
    )
    assert providers.WalmartCAProvider().matches("https://www.walmart.ca/en/ip/x/1")
    assert providers.JsonLdProvider().matches("https://store.example.com/p/1")


def test_resolve_provider_specific_first():
    assert isinstance(
        providers.resolve_provider("https://www.bestbuy.ca/en-ca/product/1"),
        providers.BestBuyCAProvider,
    )
    assert isinstance(
        providers.resolve_provider("https://www.walmart.ca/en/ip/1"),
        providers.WalmartCAProvider,
    )


def test_resolve_provider_costco_is_manual():
    assert isinstance(
        providers.resolve_provider("https://www.costco.ca/p/galaxy-s26-fe/123"),
        providers.ManualProvider,
    )


def test_resolve_provider_generic_fallback():
    assert isinstance(
        providers.resolve_provider("https://store.example.com/product/1"),
        providers.JsonLdProvider,
    )


def test_manual_provider_fetch_raises():
    with pytest.raises(RuntimeError, match="pricepulse record"):
        providers.ManualProvider().fetch("https://www.costco.ca/p/1")
