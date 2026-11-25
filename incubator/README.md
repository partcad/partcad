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
([`_shared/distributor.py`](_shared/README.md)) built on PartCAD's own `plugin_models`. All four
have repositories of their own now; what is left here is the toolkit they share.

| Package | Store | Catalogue | Models |
| --- | --- | --- | --- |
| [`partcad-svc-commerce-digikey`](https://github.com/partcad/partcad-svc-commerce-digikey) | DigiKey numbers, and any manufacturer's part by MPN, in your currency | DigiKey's categories, searched | where DigiKey links a model file; else SnapMagic's, by an alias of its `snapmagic` package |
| [`partcad-svc-commerce-octopart`](https://github.com/partcad/partcad-svc-commerce-octopart) | the cheapest authorized offer among every distributor | Octopart's categories, searched; parts are `<MPN>~<manufacturer>` | the STEP in the KiCad library |
| [`partcad-svc-commerce-mscmaster-carr`](https://github.com/partcad/partcad-svc-commerce-mscmaster-carr) (McMaster-Carr) | McMaster-Carr numbers, by the pack | by part number | McMaster-Carr's STEP; a mock server to test against |
| [`partcad-svc-commerce-mouser`](https://github.com/partcad/partcad-svc-commerce-mouser) | Mouser numbers, and any manufacturer's part by MPN | searched, nothing to build | none |

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

* **A catalogue that is searched, not listed, was invisible to `pc list packages`.** Fixed in
  PartCAD along with this work: `pc list packages <package>` lists a package's sub-packages
  (a catalogue's categories among them) with the descriptions their plugin gives, a package
  that searches itself counts as having something in it, and `-a/--all` lists a complete
  subtree. A search is recursive by default, and a plugin whose search at the top covers its
  tree (`searchScope: tree`) is asked once rather than once per category.
* **A store and its catalogue keep their credentials apart.** `pc login` saves a plugin's
  keys under that plugin's name, so a package whose provider and repository use one API is
  logged in to twice. A package-level credential, or a provider that names the repository it
  shares keys with, would make it once.
* **`distributor.py` is a copy in each package**, kept byte-identical by a digest, which is
  how `plugin_models` started. `_shared/` here is the copy to edit, and `_shared/copy.sh`
  puts it into the incubated packages and into the checkouts of the graduated ones named on
  its command line. Once these packages have proved themselves it belongs in PartCAD's
  wrappers as `plugin_distributors.py`, tested with the rest of PartCAD.
* **A relative reference climbed one level only.** Fixed in PartCAD along with this work:
  `resolve_resource_path` resolves every `..` (`//a/b/c` + `../..` is `//a`), so a
  catalogue's categories could name their package's store relatively (`../..:digikey`). The
  plugins still name it by the index's path (`provider_name` in `distributor.py`) until a
  PartCAD release that has the fix is the oldest one they support.

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

## Places in Google Earth

A repository plugin of another kind was incubated here and has moved out, with its history,
to [partcad/partcad-repo-google-earth](https://github.com/partcad/partcad-repo-google-earth): it
serves a place in Google Earth - named by its middle and its size - as parts, the ground from
Google's Elevation API and what stands on it from Google's Photorealistic 3D Tiles, each a solid
made when it is built, with the user's own Google Maps Platform key (`pc login`). Nothing of
Google's is in the package, and its metadata says `"persist": false`, so PartCAD keeps none of
what it serves beyond the process that fetched it. The index publishes it as
`//pub/collection/google-earth`, beside the other collections, once a PartCAD that keeps a
package's answers for the process only is released.

## FieldCraft as a solver

[FieldCraft](https://github.com/tangency-labs/fieldcraft) (tangency-labs, MIT or Apache-2.0) is a clean-room
CAE application in Rust: a desktop app, a command line and an MCP server over one engine of ~160 commands,
with **solvers of its own** rather than wrappers -- linear static, nonlinear static (large deformation,
plasticity, hyperelasticity, mortar contact with friction), linear buckling, block Lanczos modes, steady and
transient heat, coupled thermal stress, explicit dynamics (impact, drop, erosion), and a D3Q19 lattice
Boltzmann flow solver (turbulence models, conjugate heat transfer into conducting solids, fans with curves,
porous vents, free surfaces) on the CPU or the GPU. It meshes for itself too -- constrained Delaunay
tetrahedra, swept, mapped and multi-block hexahedra, an all-hex octree mesher -- and writes Abaqus, Nastran,
LS-DYNA and OpenFOAM decks. It is young (first commit October 2026, 0.8.1 on 18 November 2026, ~1,300
commits, ~2,900 tests and an oracle of 116 cases with closed-form or reference answers) and moving fast.

What decides how PartCAD can use it:

* **One self-contained executable per platform** -- Linux x86_64 (glibc 2.35+), macOS on Apple silicon,
  Windows x64 -- linking only the C library. No Python package, no image, no installation needed. No Linux
  arm64 build is published (its Nix flake builds one).
* **Every interface runs the same commands**, but only MCP answers them all: `fieldcraft-cli run script.json`
  prints the model summary and drops each command's reply; `fieldcraft-cli mcp`'s `batch` tool returns them.
* **It reads gmsh's MSH 4.1** (`mesh.import.orphan`), each physical group a set -- so PartCAD's port-to-face
  machinery carries over untouched. Its own meshers work on STEP it imports through SolidCraft, but name
  faces opaquely and report no per-face centroid or area, so a PartCAD port cannot yet be matched to one.
* **It judges nothing** structural: no allowable, no safety factor (only the flow solver compares a solid's
  temperature with a limit). Every threshold is the caller's.

### What was built

[`partcad-cae-fieldcraft`](partcad-cae-fieldcraft/README.md): all four of PartCAD's analyses, plus linear
buckling as an option of `fea`, on the same contract as `partcad-cae-calculix` and the others. PartCAD
imprints the ports and gmsh meshes the part as for every other implementation; the mesh is written as MSH 4.1
and handed to `fieldcraft-cli mcp --headless`, confined to the case directory, with one `batch` of engine
commands; the fields come back as VTU and are drawn by `cae_support.write_glb()`. The flow analysis poses the
part to the lattice Boltzmann solver inside out -- its bounding box, with everything that is not the part as an
obstacle -- which is exact for ports on the faces of that box and refused, with the reason, anywhere else.

It is the first CAE package that needs **no container and no installation**: without a `fieldcraft-cli` on
the machine it fetches the release it pins and checks the SHA-256 the release states. Unlike the other
directories here it already carries what its repository needs: a `LICENSE.txt`, a `.gitignore`, a
`Test` workflow running its `pytest` against the real release on all three platforms, and an `Image`
workflow for the image a `dockerImage:` pin could name later.

### Status

Run end to end through PartCAD 0.10.37 -- `pc cae fea|dynamic|thermal|cfd` on the conformance cantilever and
pipe of `examples/feature_cae`, with PartCAD's own sandbox, port imprint and gmsh -- against
`fake_fieldcraft.py`, a stand-in that speaks FieldCraft's MCP protocol, holds the mesh to the rules of
FieldCraft's MSH reader (ported from `crates/io/src/gmsh.rs`) and refuses definitions naming what does not
exist. **Not yet run against a real `fieldcraft-cli`.** The tests that do are written and skip until one is
there: `PARTCAD_FIELDCRAFT_TEST_DOWNLOAD=1 pytest` in the package fetches it, and their numbers belong in the
table in `examples/feature_cae/README.md`. Of the four, the flow is the least certain.

### What else FieldCraft could do for PartCAD

Roughly in order of value for the effort. The first three are plugins and need nothing from PartCAD; the
rest need PartCAD to grow a concept, and FieldCraft is what makes each of them worth growing.

| | what | kind | effort |
| --- | --- | --- | --- |
| 1 | Hand an analysis to FieldCraft's desktop app, or to a commercial solver | `export:` and `open:` plugins | small |
| 2 | Linear buckling as an analysis of its own | `cae:` + a fifth analysis in core | small |
| 3 | Cooling of an electronics enclosure | an assembly-level analysis | large, and the most valuable |
| 4 | Assemblies analysed as assemblies, joined where their interfaces connect | core: `cae` on assemblies | large |
| 5 | Drop tests, snap fits and seals as qualification | `qual: sim:` plugin on explicit and nonlinear solves | medium |
| 6 | Numbers, not sentences: an analysis's measurements as data | core: the `cae` result contract | small |
| 7 | Design studies over a part's parameters | core: `pc cae study` | medium |

**1. `export:` and `open:` for an analysis.** The same batch the plugin sends, ending in `file.save_as`
instead of a solve, is a `.fieldcraft` model -- the mesh, the sets, the material, the conditions, the step --
that the FieldCraft app opens ready to solve, refine and look at; ending in `deck.write` it is an Abaqus `.inp`,
a Nastran bulk data file or an LS-DYNA keyword file. So: an `export:` file type per format
(`pc export -t inp :bracket` writes the `fea` scenario as an Abaqus deck, with every condition where PartCAD
put it), and an `open:` entry for FieldCraft (`pc ide open --with fieldcraft :bracket`) converting to
`.fieldcraft` first, exactly as `open:` converts a script to STEP for FreeCAD. It is the way out of PartCAD for
an analyst who needs a solver PartCAD has no implementation for, and the way into a GUI when a result looks
wrong. The export needs a request carrying the scenario's conditions, which the `cae:` path already builds --
a small generalisation in `wrapper_export`.

**2. Buckling as an analysis.** It is an option of `fea` here because PartCAD's analyses are a fixed four.
Buckling answers a different question with a different pass criterion (a load factor, not a stress) and
belongs beside them as `pc cae buckle` with `min_load_factor`; CalculiX and Code_Aster, behind two of the six
existing packages, solve it too.

**3. Cooling of an electronics enclosure** -- the case FieldCraft's flow solver was built around (its
`cooling-enclosure`, `cooling-aio` and heat-sink samples). Its flow domain takes **conducting solids with a
power and a temperature limit**, **fans with a pressure-flow curve**, and **porous vents with a loss
coefficient**, solves the air and the solids together, and reports each solid's peak against its limit. An
enclosure is a PartCAD assembly, and everything that question needs is a property of its parts: a board's
dissipation and a chip's junction limit, a fan's
curve from its datasheet, a grille's open area. So: `power`, `maxTemperature`, a fan curve and a loss
coefficient as part properties (in `physics:` or the material), and a `cooling:` analysis of an assembly
whose implementation builds one domain from every part in it -- `pc cae cooling :enclosure`, failing the
assembly when a component runs hotter than it may. Nothing else in PartCAD's ecosystem can answer it.

**4. Assemblies as assemblies.** PartCAD analyses one part at a time; the `/pc:sim-assembly-fea` skill
carries the loads a simulation measured on each part into that part's `fea:`. FieldCraft has **ties** (dual
mortar, between non-matching meshes) and **contact**, and PartCAD already knows where every part of an
assembly touches the next: its interfaces and the connections between their ports. So an `fea:` on an
assembly could mesh each part on its own, tie each pair of connected port faces (or put a contact pair there,
for a joint that may open), and solve the whole -- bolted joints, brackets on frames -- with no hand-made
interface definition. It needs `cae` on assemblies in core, and a way for an implementation to receive several
meshes and the pairs of face groups between them.

**5. Drop tests, snap fits and seals as qualification.** PartCAD's `qual: sim:` runs MuJoCo and Gazebo:
rigid bodies. FieldCraft's explicit solver drops a deformable part on a rigid wall (with plasticity, damage
and erosion), and its nonlinear static solver presses a rubber seal or bends a snap-fit hook through contact.
Both fit the simulation contract (a file in, `before` and `after` out): a `partcad-sim-fieldcraft` whose
`after` reports peak stress, plastic strain and eroded elements lets a validation read
`after['max_plastic_strain'] < 0.02` -- "survives a 1 m drop" as a test. It needs a scene format FieldCraft
reads, which is the open part: MSH per body, or STEP through SolidCraft once faces can be matched (see the
asks below).

**6. Measurements as data.** Every implementation says what it measured in a warning string -- "Peak von Mises
stress 60.43 MPa ..." -- and tests, the conformance table and any requirement on a number have to parse it.
A `metrics` key beside `findings` in the `cae:` result (`{"max_von_mises": {"value": 6.043e7, "unit": "Pa"},
...}`, one vocabulary across implementations, as `qual: sim:` already has for `before` and `after`) would let
`pc cae --json` report them, a requirement bind to one ("tip deflection under 0.3 mm"), and the conformance
suite carry its closed forms as `expected:` with a tolerance -- FieldCraft's own oracle (`tests/oracle/*/
expected.json`: a command, a JSON pointer, a value and a tolerance) is the pattern -- so that `pc qual test`
in `examples/feature_cae` checks every implementation against the arithmetic and the README table is
generated rather than typed.

**7. Design studies.** A PartCAD part is parametric and FieldCraft is fast and free to run many times:
`pc cae study -p thickness=2:6:0.5 :bracket` running a scenario over a parameter range and reporting mass
against safety factor, or searching for the lightest one with no findings, is a loop in the client over
machinery that exists. FieldCraft has design studies on its own roadmap; PartCAD's parameters are where the
geometry side of one lives.

### What PartCAD itself could do better, found on the way

* **`cae_support.mesh()` writes MSH 2.2 only**, which FieldCraft refuses; the package writes 4.1 itself from the
  `Mesh` object. An `msh_version` argument (gmsh writes 4.1 natively) would remove ~80 lines from it and from
  the next such package.
* **A plugin that fetches a pinned tool** has nowhere shared to keep it: this package uses
  `~/.partcad/tools/`, which nothing else in PartCAD knows about or cleans up. A `plugin_tools.fetch(url, sha256)` in
  PartCAD's wrappers -- one cache, one checksum rule, pruned with the rest -- would serve every plugin whose
  tool is a downloadable binary (FieldCraft, and command-line slicers, KiCad CLI builds, OpenSCAD AppImages).
* **The `excused only without a container runtime` rule** assumes that a plugin either names an image or
  needs nothing native. A plugin that can fetch its tool is a third case: it can run anywhere its platform
  list covers, and on an unlisted platform (Linux arm64 here) it fails where a skip would be truer. A
  declared `platforms:` on a file type would let `pc qual test` say "not on this platform" the way the
  feature_cae example's `unless: [aarch64]` does by hand.

### What to ask FieldCraft for

All small, all in its interest too, and each one widens what the package can do:

* **Pressure and velocity conditions on obstacle faces** in the flow solver. Today only the box's faces let
  fluid in and out, which is why a port must lie on the part's bounding box; with this, any port of any part
  could be an inlet.
* **A face's centroid, area and normal in `geometry.bodies`**, or reading a STEP's face names through. Either
  would let PartCAD match its port faces to FieldCraft's, and so use FieldCraft's own meshers -- its swept and
  octree hexahedra are its strength, and far more accurate per degree of freedom on thin parts than tetrahedra.
* **`results.export.vtu` for fluid steps** ("not supported yet"), so the model drawn for a flow is the field
  itself rather than a probe of it at the walls.
* **A Linux arm64 release**, which its Nix flake already builds.
* **`fieldcraft-cli run --replies`**, printing each command's reply as JSON lines: the simplest possible
  machine interface, and one a plugin could use without speaking MCP.

### Next

1. Run the package's tests with `PARTCAD_FIELDCRAFT_TEST_DOWNLOAD=1` against the real release, fix what the
   real solver disagrees with (most likely in the flow), and put its numbers in `examples/feature_cae/README.md`.
2. Move it out: `git subtree split --prefix incubator/partcad-cae-fieldcraft -b fieldcraft` and push to
   `partcad/partcad-cae-fieldcraft`; then the index (below), and the solver tables in
   `docs/source/digital_thread/lifecycle/analysis.rst`, `docs/source/plugins/analyses.rst` and
   `examples/feature_cae/README.md`.
3. The `export:`/`open:` pair (1 above), which needs nothing from PartCAD.
4. Propose `metrics` (6) and `msh_version` in PartCAD, then buckling (2) and cooling (3).

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

and the same for `octopart`, `mcmaster` (whose repository's name still has a typo to fix
first: `partcad-svc-commerce-mscmaster-carr`) and `mouser`.

`partcad-cae-fieldcraft` goes beside the other solvers in the index's `feature/cae/partcad.yaml`, as
`//pub/feature/cae/fieldcraft`, the name its `partcad.yaml` already gives itself:

```yaml
  # FieldCraft: stress and buckling, modes, heat and lattice Boltzmann flow, by
  # its own solvers. Needs no container: it fetches a checksum-pinned release.
  fieldcraft:
    desc: Static stress and buckling, modal, heat transfer and flow analysis by FieldCraft.
    type: git
    url: https://github.com/partcad/partcad-cae-fieldcraft
    track: main
    revision: <commit>
```

## Testing

Each package's tests run in its own repository's CI, and by hand there with `pytest`; they need
PartCAD's `plugin_models`, which `conftest.py` finds in an installed `partcad` (`pip install
--no-deps partcad` is enough), in `$PARTCAD_WRAPPERS`, or in a PartCAD checkout beside the
package's own. The toolkit's own tests, and the FieldCraft package's, run here:

```shell
cd incubator/_shared && pytest -c /dev/null --rootdir . .
cd incubator/partcad-cae-fieldcraft && pytest -c /dev/null --rootdir . .
```

`-c /dev/null` keeps this repository's own pytest configuration, which is PartCAD's, out of
it. The shared files are edited in `_shared/` and copied out with `_shared/copy.sh`, into
checkouts of the packages' repositories beside this one:

```shell
incubator/_shared/copy.sh ../partcad-svc-commerce-digikey ../partcad-svc-commerce-octopart \
  ../partcad-svc-commerce-mscmaster-carr ../partcad-svc-commerce-mouser
```
