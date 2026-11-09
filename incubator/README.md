# Incubator: PartCAD packages waiting for repositories of their own

A PartCAD plugin is a package, and a package belongs in a repository of its own that the
public index (`partcad/partcad-index`) pins. The packages here are not there yet: each
directory is one future repository, named as it will be, and moves out whole, with its
history:

```shell
git subtree split --prefix incubator/partcad-svc-commerce-digikey -b digikey
git push git@github.com:partcad/partcad-svc-commerce-digikey.git digikey:main
```

A repository needs what a directory here does not carry: a `LICENSE` (Apache 2.0, as the
scripts say), a `.gitignore` for `__pycache__/`, and a CI job running its `pytest`. The
index's `svc/commerce/partcad.yaml` then pins it beside the other stores (see
[Into the index](#into-the-index)). Nothing here is built, packaged or tested by
PartCAD's CI (the linters still read it); each package's tests are run by hand, as below.

## Distributors as both a store and a catalogue

PartCAD knows a distributor two ways, and few of the ones in the index are both:

* a **store** - a `store` provider, asked `avail` and `quote` for a `vendor` and a `sku`;
* a **catalogue** - a repository plugin serving the distributor's products as parts, with
  their geometry, each saying the `vendor` and `sku` to buy it by and listing the store as its
  supplier.

IKEA (`partcad-svc-commerce-ikea`) is both, with its catalogue drawn from models on model
sites. The question here was which distributors are both **natively**: one purpose-built API
that answers the categories, the search, the 3D models and the prices.

### What was evaluated

Eleven distributors, each researched against its official developer documentation and, where
one was published, its OpenAPI or GraphQL schema (DigiKey's and Mouser's Swagger files,
Nexar's introspection, TrustedParts' and OnlineComponents' OpenAPI, McMaster-Carr's Postman
collection, PartsTech's OpenAPI).

| | API | Categories | Search | 3D models | Prices & stock | Access | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **DigiKey** | Product Information v4, REST | yes, a tree | yes, per category, parametric | links only; mostly a CAD partner's page | yes, per packaging, by locale | free app, OAuth2; 1,000 calls/day | **built** - store and catalogue |
| **Octopart** (Nexar) | GraphQL | yes, a tree (free) | yes, per category | yes: STEP inside the KiCad library | every authorized seller's offers | free app, small monthly part quota | **built** - the best catalogue |
| **McMaster-Carr** | Product Information, REST | no | no: lookup by part number | **yes, STEP for almost every part** | price breaks, USD; no stock | approved customers, client certificate | **built** - by part number |
| **Mouser** | Search API, REST | no | yes | no | yes | free key; 1,000 calls/day | **built** - store, search only |
| Arrow | ItemService v4, REST | no | part-number prefix only | no | yes; ordering API | by request, ~a week | store-only candidate |
| TrustedParts.com | Inventory API v2, REST | no | by MPN only | no | every authorized seller's offers | free key, by request | store-only candidate |
| OnlineComponents.com | Master Electronics `wapi` v1 | strings only | by part number | no | yes; cart, order, quote APIs | self-serve key | store-only candidate |
| MISUMI | none public (a partner API in Japan, punch-out/EDI elsewhere) | - | - | website only, configured, login | - | partnership | not a fit today |
| Grainger | none public (per contract; a customer API team formed in 2026) | - | - | website only | punch-out, EDI | account rep | not a fit today |
| Fastenal | a gated developer portal, contents unknown | ? | ? | website only | punch-out, EDI | registration | worth registering to see |
| PartsTech | REST, OpenAPI | automotive (PCdb) | by vehicle only | none | per store; punch-out | partners only | not a fit: automotive, terms |

**None of them hands out a STEP file freely over an API.** McMaster-Carr comes closest, to
its approved customers; Octopart's comes inside an ECAD library and may depend on the plan;
DigiKey's are mostly links to SnapEDA or Ultra Librarian, which want a sign-in of their own;
Mouser, Arrow, TrustedParts and OnlineComponents have none. The one documented, headless way
to a manufacturer's STEP by part number found is **TraceParts' API**
(`api-gateway.traceparts.com`, an API key by request) - a catalogue of its own rather than a
distributor, and the natural next plugin (see [Next](#next)).

Every one of these APIs wants each user's own credentials and forbids sharing them, and
most limit how long their answers may be kept. So every plugin here logs in with the user's
own keys (`pc login`), lists nothing - a catalogue is searched, never enumerated - and keeps
answers briefly: prices an hour, products and searches a day.

### What was built

Four packages, each one script serving both plugins, on a toolkit they share
([`_shared/distributor.py`](_shared/README.md)) built on PartCAD's own `plugin_models`. Three
have repositories of their own now; Mouser is still here.

| Package | Store | Catalogue | Models |
| --- | --- | --- | --- |
| [`partcad-svc-commerce-digikey`](https://github.com/partcad/partcad-svc-commerce-digikey) | DigiKey numbers, and any manufacturer's part by MPN, in your currency | DigiKey's categories, searched | where DigiKey links a model file; else SnapMagic's, by an alias of its `snapmagic` package |
| [`partcad-svc-commerce-octopart`](https://github.com/partcad/partcad-svc-commerce-octopart) | the cheapest authorized offer among every distributor | Octopart's categories, searched; parts are `<MPN>~<manufacturer>` | the STEP in the KiCad library |
| [`partcad-svc-commerce-mscmaster-carr`](https://github.com/partcad/partcad-svc-commerce-mscmaster-carr) (McMaster-Carr) | McMaster-Carr numbers, by the pack | by part number | McMaster-Carr's STEP; a mock server to test against |
| [`partcad-svc-commerce-mouser`](partcad-svc-commerce-mouser/README.md) (here) | Mouser numbers, and any manufacturer's part by MPN | searched, nothing to build | none |

What they have in common, and what is new about them:

* **A catalogue part says how to buy it.** Every part carries `vendor` and `sku` (and
  `count_per_sku` for a pack), and every category lists the package's own store as its
  supplier, so `pc supply quote` of a catalogue part, or of an assembly made of them, finds
  the store with nothing more to declare.
* **One part, one alias per pack.** Where a distributor sells one manufacturer's part in
  several packagings (DigiKey's cut tape, reel and Digi-Reel), the catalogue serves the part
  once, as `<MPN>~<manufacturer>`, bought by its MPN from whoever has it, and each packaging as
  an alias of it with its own SKU and `count_per_sku`. PartCAD treats a part as bought when an
  alias of it that names a vendor and an SKU is loaded, and orders it by the alias whose pack
  suits the quantity - so an assembly links the part, not a packaging of it.
* **A store quotes more than its own catalogue.** A part declared anywhere with a
  manufacturer as its `vendor` and the manufacturer's part number as its `sku` is looked up by
  that MPN - the cheapest packaging (DigiKey, Mouser) or the cheapest authorized seller
  (Octopart) for the quantity. Octopart's parts are named and bought that way, so its
  catalogue is quoted by DigiKey's and Mouser's stores as well as its own.
* **A quote is for the quantity actually ordered**: raised to the minimum and to the order
  multiple, at the price break it then reaches, in the currency the distributor says - and
  stock is said per line, never refused.
* **A product with no model is found, not served**: a search lists it, says it has no 3D
  model and says the `vendor` and `sku` to quote it by, without claiming a part it cannot build.

### Status

All four are tested against their APIs' documented shapes, answered from tables, none
touching the network. DigiKey (with SnapMagic), Octopart and McMaster-Carr have also been run
end to end in PartCAD 0.9.22 - a search, a part built from its model, a quote - against servers
standing in for their APIs: McMaster-Carr's is `mock_mcmaster.py` in its repository, over TLS
with a client certificate, and each plugin takes an `api` parameter to be pointed at one. None
has been run against a live API yet, for want of credentials here; a run with real keys should
confirm what the documentation could not: DigiKey's media types for model files, whether
Octopart's KiCad downloads need a sign-in on the user's plan, McMaster-Carr's pack wording, and
Mouser's `RawPrice`. Each package's README says what it cannot do yet.

Two things PartCAD itself could do better, found on the way:

* **A catalogue that is searched, not listed, is invisible to `pc list packages`.**
  `Context.get_packages(has_stuff=True)` keeps a package only if it lists an object, so the
  categories of DigiKey's and Octopart's catalogues are neither listed nor found by
  `pc search packages` (and `pc list packages <one of them>` shows no description, since a
  plugin's metadata is not applied before it is printed). A package that searches itself
  (`searchKinds`) could count as having something to look at - with a recursive search then
  asking only the top of a plugin's tree, which a distributor's search covers, rather than a
  thousand categories one by one. Until then the categories are found by name, and each
  package's description names the ones below it.
* **A store and its catalogue keep their credentials apart.** `pc login` saves a plugin's
  keys under that plugin's name, so a package whose provider and repository use one API is
  logged in to twice. A package-level credential, or a provider that names the repository it
  shares keys with, would make it once.
* **`distributor.py` is a copy in each package**, kept byte-identical by a digest, which is
  how `plugin_models` started. `_shared/` here is the copy to edit, and `_shared/copy.sh`
  puts it into the incubated packages and into the checkouts of the graduated ones named on
  its command line. Once these packages have proved themselves it belongs in PartCAD's
  wrappers as `plugin_distributors.py`, tested with the rest of PartCAD.
* **A relative reference climbs one level only.** A catalogue's categories would name their
  package's store relatively (`../..:digikey`), so that the package works wherever it is
  imported; but `resolve_resource_path` collapses `..` in a single pass, and
  `//a/b/c` + `../..` resolves to `//a/b/c/..`. So the plugins name their store by the
  index's path, as IKEA's do.

### Next

* Live runs with real keys, then the index (below).
* **TraceParts**, as a catalogue of its own (`partcad-repo-traceparts`, beside the model
  sites): manufacturers' catalogues, categories, and a STEP by part number over a documented
  API. It is what would give Mouser's, Grainger's and Fastenal's products geometry, by their
  manufacturers' part numbers.
* **TrustedParts.com and OnlineComponents.com** as store-only packages: a few dozen lines each
  on the same toolkit, quoting by MPN (TrustedParts every authorized seller, OnlineComponents
  its own stock, with a cart).
* Carts: Octopart's `supOctocart` and Mouser's cart API can answer a quote's `cartId`.
* Fastenal: register at its developer portal to see what it offers.

## Into the index

Once a package has a repository, `svc/commerce/partcad.yaml` in `partcad/partcad-index`
pins it beside the other stores:

```yaml
  # DigiKey: quotes DigiKey part numbers, and any manufacturer's part by MPN;
  # and DigiKey's range, by DigiKey's categories. Needs an API app of the user's own.
  digikey:
    desc: DigiKey, quoted for your country; and its range, by DigiKey's categories.
    type: git
    url: https://github.com/partcad/partcad-svc-commerce-digikey
    track: main
    revision: <commit>
```

and the same for `octopart` and `mcmaster` (whose repository's name still has a typo to fix
first: `partcad-svc-commerce-mscmaster-carr`), and later `mouser`.

## Testing

Each package's tests need `pytest` and PartCAD's `plugin_models`, which `conftest.py` finds in
an installed `partcad` (`pip install --no-deps partcad` is enough), in `$PARTCAD_WRAPPERS`, or
in a PartCAD checkout - this one, or one beside the package's own:

```shell
cd incubator/partcad-svc-commerce-mouser && pytest -c /dev/null --rootdir . .
```

`-c /dev/null` keeps this repository's own pytest configuration, which is PartCAD's, out of
it. The shared files are edited in `_shared/` and copied out with `_shared/copy.sh`:

```shell
incubator/_shared/copy.sh ../partcad-svc-commerce-digikey ../partcad-svc-commerce-octopart \
  ../partcad-svc-commerce-mscmaster-carr
```
