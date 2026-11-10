# Mouser for PartCAD

Mouser, published with the other stores as `//pub/svc/commerce/mouser`:

* **a store**, `//pub/svc/commerce/mouser:mouser`, that quotes Mouser part numbers - and any
  manufacturer's part Mouser lists, by its manufacturer and part number - at Mouser's prices,
  in your account's currency, with Mouser's stock, minimum and order multiple;
* **a searchable catalogue**, `//pub/svc/commerce/mouser/products`: Mouser's own search, each
  product it finds listed with the Mouser part number to quote it by.

Both are one script, `mouser.py`, asking **Mouser's Search API** (<https://api.mouser.com/api/docs/ui/index>).

Mouser is the store half of the pair here and not the catalogue half: its API has **no
category tree and no 3D models**, so nothing it finds is a part to build. Pair it with a
catalogue that has models - Octopart's parts say their manufacturer and part number, which this
store quotes.

## Setting it up

The Search API key is free: sign in to My Mouser, fill in the form at
<https://www.mouser.com/api-search/>, and copy the key (it is also under My Mouser > APIs; the
Cart and Order keys are other keys). Then:

```shell
pc login //pub/svc/commerce/mouser:mouser_repo
pc login //pub/svc/commerce/mouser:mouser
```

(or `MOUSER_API_KEY`). Mouser takes the key in the query string of every request.

## Using it

```shell
pc search parts -P //pub/svc/commerce/mouser/products -k LM358
pc supply quote --provider //pub/svc/commerce/mouser:mouser :my-op-amp#10
pc supply quote --provider //pub/svc/commerce/mouser:mouser //pub/svc/commerce/octopart/products:BAV99~nexperia#100
```

## How Mouser is asked

| What PartCAD asks | Mouser Search API |
| --- | --- |
| a search | `POST /api/v1/search/keyword` (`SearchByKeywordRequest`), at most 50 |
| a Mouser number, a manufacturer's number | `POST /api/v1/search/partnumber` (`SearchByPartRequest`, `Exact`) |

A failure is a 200 with `Errors` in it, which is said and not kept. Prices are read from
`RawPrice` where Mouser gives it, and otherwise from `Price`, which is written for a person
(`"6,85 €"`).

## What it cannot do (yet)

* No categories, no models (see above).
* **30 requests a minute, 1,000 a day.** Prices are kept for an hour and searches for a day.
* No cart or order: Mouser has both APIs, with keys of their own; a quote could fill a Mouser
  cart and answer its `CartKey` as the `cartId` in a later version.
* Mouser's API terms license its data for display in your application; keys are your own.

Not yet run against the live API: the tests answer it from a table in the shapes of Mouser's
Swagger.

## Tests

```shell
pip install partcad pytest
pytest
```
