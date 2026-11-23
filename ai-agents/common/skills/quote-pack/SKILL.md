---
name: quote-pack
description: Prepare the basis for quoting a customer for building N of a PartCAD part or assembly - what has to be bought and how much of it (rounded up to the packs it is sold in, priced where a supplier answers), what has to be made and from how much of which material, how many assembly steps it takes, and what is still unknown - as a costing CSV, a quote-basis sheet and a manifest tracing every figure to the package, the commit and the command that produced it. Use for /pc:quote-pack, or when the user asks what it costs to build something, for a cost roll-up, a costed bill of materials or an estimate, or when a quoting skill of another plugin, such as Claude for Manufacturing, needs the product's bill of materials and cost drivers. It leaves rates, margins and prices nobody quoted blank for the estimator, and never orders.
---

# pc:quote-pack

Gather everything an estimator needs to quote building a product, from the
product's own definition. `$ARGUMENTS` names the object and how many are to be
built, and may name a supplier to price at and where to write the result.

This is the *selling* side, and `/pc:rfq-pack` the *buying* side: that one
writes what a supplier is asked to make; this one adds up what building the
product takes, so somebody can put a price on it. They read the same lines, and
an estimator may well send an RFQ for the made parts and drop the replies into
this.

**PartCAD knows quantities, materials, sizes and masses. It does not know a
labour rate, a machine rate, an overhead or a margin, and neither do you.**
Leave every one of those blank, as an input, and say so. A cost roll-up with an
invented rate in it looks finished, and is the most expensive kind of wrong a
quote can be.

## 1. Settle what is asked

- **The object** — a part or an assembly. Find it as `/pc:export` §1 does.
- **The quantity** — how many are to be built. Ask if it was not said: pack
  sizes, minimum orders and set-up costs make the cost of one different from
  the cost of a hundred, divided by a hundred.
- **Whether to ask suppliers for prices** — `pc supply quote` asks the
  providers the package names (§4). Ask before running it when a provider is a
  real store: it is a request to somebody else's service.
- **The destination** — as `/pc:rfq-pack` §1, defaulting to
  `./out/quote/<object>-<quantity>-<YYYY-MM-DD>/`.

## 2. Make sure PartCAD is available, and pin the revision

Exactly as `/pc:rfq-pack` §2: resolve `pc`, pass `--no-ansi` and capture both
streams, use the `partcad` MCP server's tools where there is no shell, and
record the PartCAD version, the commit, any tag on it and whether anything is
uncommitted. A quote is a promise about a revision; say which.

## 3. Work out the lines

Read the tree of the object as `/pc:rfq-pack` §3 does — the
`manufacturing.tree` daemon method through the MCP server's `execute`, or the
assembly instructions with `-r -b` — and sort every line into one of:

| Line | What it is | Where its figures come from |
| --- | --- | --- |
| **buy** | a part or an assembly bought whole: it declares a `vendor:` and an `sku:` | `pc bom -j` |
| **stock** | what a made part is cut from: a sheet, a bar, a board | `pc bom -j`, kind `stock` |
| **make** | a part made here, or by a supplier from its model | `pc info`, as `/pc:rfq-pack` §4 |
| **assemble** | an assembly put together here | the assembly instructions |

```sh
pc --no-ansi bom -j <object> 2>/dev/null      # JSON on stdout, the log on stderr
```

The bill of materials lists what is *procured*: bought items and stock, each
with its `count`, `vendor`, `sku`, `count_per_sku` (how many come in what one
SKU buys) and `desc`. Its `software` lines are files, not purchases — list them,
cost them at nothing unless the user says otherwise. A part that is printed
names no stock, so it appears in no line of the bill of materials: its material
is its mass.

Multiply every count by the quantity being built. Then, for each bought or
stock line, the **order quantity** is the count rounded up to whole SKUs:
`ceil(count / count_per_sku)` SKUs. One stock item is counted per part made
from it — PartCAD does not nest parts on a sheet yet — so a stock quantity is an
upper bound, and the quote-basis sheet says so.

A line with `problems`, or that can be neither bought nor built, goes into
*Open items*, never into a subtotal.

## 4. Prices

Only where a supplier gives one. With the user's agreement:

```sh
pc --no-ansi supply quote -j --ignore-missing <object>#<quantity> 2>/dev/null
```

`#<quantity>` is how many; `--ignore-missing` quotes what can be had and leaves
out what nobody supplies, instead of failing; `-p <provider>` asks one
provider; `--cheapest` prices every pack an alias offers and takes the
cheapest. The answer is a JSON object keyed by supplier, each with a `result`
holding its `price`, its `currency` and the `cartId` it is held under, or `{}`
when nobody answered. A quote expires: record when it was asked.

Write a price into the CSV only from that answer, with the supplier as its
source. **Do not run `pc supply order`**, which places the order.

Everything else is priced by the estimator. Where they already have figures —
prices from earlier jobs, replies to an RFQ, a price list — and give them to
you, use them and name each one's source.

## 5. Cost drivers of what is made and assembled

For each **make** line, read `pc --no-ansi info <part>` and record what a
manufacturing cost is driven by: the `method`, the material, the `stock`, the
size (`BoundingBox.size` — whether it fits a machine), the volume and the mass
(material used, for a printed or cast part), and the `tolerance` (machining
time rises steeply as it tightens). A part whose `manufacturing:` names a
machine (`cnc:`, `laser:`, `drill:`) can say how much cutting it takes — the
passes, how deep, and how far the tool travels in the cut (`stats.cut_length`,
in millimetres):

```sh
mkdir -p /tmp/pc-quote/cam        # -O, or pc cam writes the program beside the package
pc --no-ansi cam --json -O /tmp/pc-quote/cam <part> 2>/dev/null
```

Naming a part that declares no route is an error; skip those.

For each **assemble** line, count the steps of the assembly instructions
(`pc instructions -t html`): steps, and parts placed, are what assembly time is
quoted from.

## 6. Write the files

```
<destination>/
  costing.csv       one row per line
  quote-basis.md    the summary an estimator works from
  manifest.json     where every figure came from
```

### `costing.csv`

```
line,item,kind,description,quantity_per_build,quantity,count_per_sku,order_skus,vendor,sku,unit_price,currency,price_source,price_date,extended_price,method,material,stock,tolerance_mm,size_x_mm,size_y_mm,size_z_mm,volume_mm3,mass_g,assembly_steps,notes
```

`kind` is `buy`, `stock`, `make`, `assemble` or `software`. `unit_price` is the
price of one SKU; `extended_price` is `order_skus × unit_price`, and both are
empty where nobody quoted. Never put a figure into a cell whose source column
is empty.

### `quote-basis.md`

In this order:

1. What is being quoted: the object, the quantity, the revision.
2. **Known costs**: the bought items and stock that were priced, with their
   subtotal per currency, and when each price was given.
3. **Unpriced lines**: bought items and stock nobody quoted, with vendor, SKU
   and order quantity, ready to be priced.
4. **Make**: each made part with its method, material, size, mass and
   tolerance — what a machine-hour or a price per part is estimated from.
5. **Assemble**: the number of steps and of parts placed in each assembly.
6. **Open items**: every line with a problem, anything not stated, anything
   uncommitted, and the stock quantities that are upper bounds.
7. **Left for the estimator**, as blanks: labour and machine rates, set-up,
   scrap allowance, overhead, margin, lead time, validity of the quote.

Do not add the subtotals into a total for the product: a total of the lines
that happen to have prices is not the cost of building it.

### `manifest.json`

The same shape as `/pc:rfq-pack`'s, with `"kind": "quote-pack"`, the quantity,
and every supplier answer listed with the command that asked for it and when.

## 7. Report

Say where the files are, what share of the lines is priced and by whom, and
list the open items and everything left for the estimator. Do not present a
figure as the cost of the product.
