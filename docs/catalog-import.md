# Master catalog import format

The master catalog (`catalog_items`, [db-schema.md §3.2](db-schema.md#32-catalog-and-knowledge)) is the shared layer: the manufacturers' products, their attributes, module widths and list prices (07 §4.3, 05 §4.3). It never holds a factory's cost, sale price or supplier (10 §11). S18 decision 1 settles the format below. Until the catalog team delivers 3–5 brands (roadmap B3), `make seed` loads a sample of 20 ABB items with made-up list prices, [backend/konboro/db/catalog/abb_sample.csv](../backend/konboro/db/catalog/abb_sample.csv).

## Loading a file

```bash
cd backend && uv run python -m konboro.db.catalog path/to/catalog.csv
```

- The loader runs as the database owner, like the seed, because the app role can only read global tables.
- It upserts on `(brand, sku)`. Loading the same file again updates the rows in place and keeps their ids, so tenant products that link to an item (`products.catalog_item_id`) stay linked.
- Rows get `source` = `import` (00 §14.2).
- A file with any problem loads nothing. Every problem is listed with its line number.

## Layout

The file is UTF-8 CSV (a BOM is allowed). There is one header row, then one row per item. Columns can come in any order.

| Column | Required | Value |
| --- | --- | --- |
| `brand` | yes | The manufacturer as the catalog spells it: `ABB`, `Schneider` |
| `sku` | yes | The manufacturer's catalog number. Unique per brand in the file. This is `products.manufacturer_sku`, the key that matches a supplier's price list and an identical product (07 §7.2) |
| `family` | yes | An attribute-schema family (05 §4.4): `circuit_breaker`, `rcd`, `contactor`… Not a symbol class (`mcb`) |
| `series` | no | `S200M` |
| `model_code` | no | `S203M` |
| `module_width` | no | Width in 18 mm modules, a decimal: `3`, `2.5`. Used to size the enclosure (07 §7.4) |
| `list_price` | no | The manufacturer's list price per unit, a decimal with a dot, never a thousands separator. Brand discounts are taken off it (07 §7.2, priority 2) |
| `list_currency` | when `list_price` is set | A 3-letter code: `ILS`, `USD`, `EUR`. Converted on the quote date (07 §7.2) |
| `status` | no | `active` (the default) or `discontinued` |
| `replaced_by_sku` | no | The `sku` of the same brand's item that replaces this one. It must be in the same file |
| `attr.<name>` | no | One column per attribute in the family's schema: `attr.current_a`, `attr.poles`, `attr.curve`. An empty cell means the item has no value for it |

**Attribute values** are written the way stage 4 writes them (04 §6):
- `true` and `false` become booleans.
- Whole numbers become integers.
- Numbers with a dot become JSON numbers (`6.3`).
- Anything else stays text (`C`, `1NO+1NC`).

Current and poles are never filled in by a default (non-negotiable 4). An item whose sheet doesn't give them leaves the cells empty.

**Example**

```csv
brand,sku,series,model_code,family,module_width,list_price,list_currency,status,replaced_by_sku,attr.current_a,attr.poles,attr.curve,attr.breaking_capacity_ka
ABB,S203M-C16,S200M,S203M,circuit_breaker,3,210.00,ILS,active,,16,3,C,10
ABB,XT1C160 TMD80 3P,Tmax XT,XT1C160,circuit_breaker,,230.00,USD,active,,80,3,,25
```

## What the loader refuses

- A missing required column, or a column that is neither in the table above nor `attr.*`.
- An empty `brand`, `sku` or `family`, or the same `(brand, sku)` twice.
- A `list_price` or `module_width` that is not a number, or is negative.
- A `list_price` with no `list_currency`, or a currency that is not 3 capital letters.
- A `status` other than `active` or `discontinued`.
- A `replaced_by_sku` that is not in the file.
