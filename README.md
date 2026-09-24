# pricepulse

A small, sharp gadget price tracker for Canadian retailers. Track products,
build a price history in SQLite, and get told — loudly, but only when it
matters — when something hits a new all-time low or drops hard.

No accounts, no browser extensions, no cloud. A CLI, a database file, and
opinions about when a deal is real.

## Quickstart

```bash
pip install -e ".[dev]"

# Track something
pricepulse add "Anker 25K power bank" "https://www.bestbuy.ca/en-ca/product/..."

# Check everything, store fresh samples, print alerts
pricepulse check

# See the history, or just the floor
pricepulse history "Anker 25K power bank"
pricepulse atl "Anker 25K power bank"

# Bot-walled store (looking at you, Costco)? Log it by hand:
pricepulse record "Galaxy S26 FE" 865.99
```

Data lives in `~/.pricepulse/prices.db` by default; override per-command with
`--db path/to/file.db`.

## How alerts work

`pricepulse check` fetches every tracked product and compares the fresh
sample against history. You get an alert when:

- the price hits a **new all-time low** (strictly cheaper than every previous
  sample — a flat price at the low doesn't re-alert every run), or
- the price **dropped by at least 10%** since the previous check
  (tune with `pricepulse check --drop-pct 15`).

Example output:

```
Anker 25K power bank: 129.18 CAD (in stock)

ALERT: Anker 25K power bank — 129.18 CAD
  * new all-time low
  * down 23.5% from 169.99
  https://www.bestbuy.ca/en-ca/product/...
```

## Provider support

| Provider | Matches | Method | Honest status |
|---|---|---|---|
| Best Buy Canada | `bestbuy.ca` URLs | schema.org JSON-LD `Offer` parsing | Parsed from saved fixtures only — not verified against live pages |
| Walmart Canada | `walmart.ca` URLs | schema.org JSON-LD `Offer` parsing | Parsed from saved fixtures only — not verified against live pages |
| Generic JSON-LD | any `http(s)` URL | schema.org JSON-LD `Offer` parsing | Best effort; retailer markup varies, bot walls happen |
| Manual | `costco.ca` (auto), or anything unmatched | you type the price | For login-walled stores — Costco hides prices behind membership |

Notes:

- Marketplace listings often carry several offers; the parser takes the
  **lowest in-stock** offer. On Walmart marketplace that can be a third-party
  seller — check the seller before treating it as the headline price.
- `pricepulse check` never logs in anywhere and never touches a cart. If a
  fetch fails, it prints the error and moves on to the next product.
- Same-day delivery apps (Instacart, Uber Eats) list Costco inventory with
  visible prices and no login — handy for `pricepulse record` entries.

## Run it on a schedule

One line in your crontab — checks every Monday at 9am, appends to a log:

```cron
0 9 * * 1 pricepulse check >> ~/.pricepulse/check.log 2>&1
```

## Development

```bash
pip install -e ".[dev]"
pytest            # 36 tests, all offline — fixtures live in tests/fixtures/
```

Project layout:

```
pricepulse/
  __init__.py     version
  providers.py    Provider protocol + JSON-LD scrapers + manual fallback
  store.py        SQLite storage (products, samples)
  analysis.py     all-time-low + alert logic
  cli.py          argparse CLI, `pricepulse` entry point
tests/
  fixtures/       saved HTML pages used by provider tests (no network)
```

## License

MIT — see [LICENSE](LICENSE).
