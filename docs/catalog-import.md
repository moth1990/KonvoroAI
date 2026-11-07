# Master catalog import format

The master catalog (`catalog_items`, [db-schema.md §3.2](db-schema.md#32-catalog-and-knowledge)) is the shared layer: the manufacturers' products, their attributes, module widths and list prices (07 §4.3, 05 §4.3). It never holds a factory's cost, sale price or supplier (10 §11). S18 decision 1 settles the format below. Until the catalog team delivers 3–5 brands (roadmap B3), `make seed` loads a sample with made-up list prices (S20 decision 1): about 150 ABB and Schneider items covering the golden drawings' families, and one SATEC meter, [backend/konboro/db/catalog/sample.csv](../backend/konboro/db/catalog/sample.csv), with its kits ([sample_kits.csv](../backend/konboro/db/catalog/sample_kits.csv)) and accessory fits ([sample_accessories.csv](../backend/konboro/db/catalog/sample_accessories.csv)). After it, `make seed` loads [common.csv](../backend/konboro/db/catalog/common.csv) (S27b, with its accessory fits in [common_accessories.csv](../backend/konboro/db/catalog/common_accessories.csv)): 15 common products the user listed from three factory drawings (25/886, 2240-P-001, 25/823), each checked against the maker's data sheet, with no list price. They are real products, unlike the sample's made-up prices, so they live in a file of their own: the sample can be replaced by the real catalog without losing them. A product the list left out (no model written, or no real product with those values) reaches a quote as a line waiting for a decision (07 §7.1).

## Loading a file

```bash
cd backend && uv run python -m konboro.db.catalog path/to/catalog.csv --kits path/to/kits.csv --accessories path/to/accessories.csv
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
| `model_tokens` | no | The model codes as drawings write them, separated by `\|`: `XT1C160\|XT1C\|XT1`. Upper-cased, spaces removed. Without it, the model code alone. Stage 5 narrows to the items that list a code written beside a component (05 §5.2.1) |
| `symbol_class` | no | The class within the family, when the family has several: `mcb`, `mccb`, `motor_protection` (05 §5.1) |
| `module_width` | no | Width in 18 mm modules, a decimal: `3`, `2.5`. Used to size the enclosure (07 §7.4) |
| `list_price` | no | The manufacturer's list price per unit, a decimal with a dot, never a thousands separator. Brand discounts are taken off it (07 §7.2, priority 2) |
| `list_currency` | when `list_price` is set | A 3-letter code: `ILS`, `USD`, `EUR`. Converted on the quote date (07 §7.2) |
| `status` | no | `active` (the default) or `discontinued` |
| `replaced_by_sku` | no | The `sku` of the same brand's item that replaces this one. It must be in the same file |
| `attr.<name>` | no | One column per attribute in the family's schema: `attr.current_a`, `attr.poles`, `attr.curve`. An empty cell means the item has no value for it |

Stage 7's derived items (07 §7.4, S22) query their own families, which are never drawn as components:

| Family | Attributes the rule reads |
| --- | --- |
| `enclosure` | `attr.modules` and `attr.rows` (by modules), `attr.height_mm`, `attr.width_mm`, `attr.depth_mm`, `attr.ip` (by the drawing's dimensions, all at least), `attr.material` |
| `din_rail` | `attr.length_mm`: the shortest at least the enclosure's width |
| `busbar` | `attr.current_a`: the smallest at least the main device's current |
| `terminal` | `attr.cross_section_mm2`: per drawn cross-section |
| `label` | none |

The sample's rows of these families are illustrative, for the demo and the tests, until the master catalog (roadmap B3).

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

## Kits and accessories (05 §5.9.1)

Two optional companion files, loaded with the items (`--kits`, `--accessories`). Their rows name items by `brand` and sku; an item that is in neither the file nor the catalog fails the whole load. A rerun with the same rows changes nothing.

**Kits**: the part a main item needs.

| Column | Required | Value |
| --- | --- | --- |
| `brand` | yes | `ABB` |
| `item_sku` | yes | The main item: `XT1C160 TMD80 4P` |
| `part_sku` | yes | The part: `RC Sel 4P XT1` |
| `quantity` | no | Per unit of the main item, a whole number, 1 by default |
| `when_text` | no | The phrase in the component's text that calls for the part: `משולב פחת`. Empty: the part always comes with the item |
| `reason_he` | yes | The reason the line shows: `מודול פחת למפסק משולב פחת` |

**Accessories**: which device series an accessory fits.

| Column | Required | Value |
| --- | --- | --- |
| `brand` | yes | The accessory's brand |
| `accessory_sku` | yes | `S2C-H01` |
| `fits_brand`, `fits_series` | yes | The device's brand and `series`: `ABB`, `S200M`. Or one of its `model_tokens`, for an accessory that fits only some models of a series: `ABB`, `XT5` (YO-C XT5-XT6; "Tmax XT" runs from XT1 to XT6). Stage 5 takes the most specific fit: when an accessory fits the device by its model, one that fits only by its series is left out (BUG-109) |

## What the loader refuses

- A missing required column, or a column that is neither in the table above nor `attr.*`.
- An empty `brand`, `sku` or `family`, or the same `(brand, sku)` twice.
- A `list_price` or `module_width` that is not a number, or is negative.
- A `list_price` with no `list_currency`, or a currency that is not 3 capital letters.
- A `status` other than `active` or `discontinued`.
- A `replaced_by_sku` that is not in the file.
