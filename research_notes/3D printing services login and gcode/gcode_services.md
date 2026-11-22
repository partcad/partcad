# Print services that accept customer G-code, sliced 3MF or explicit FFF process settings (US + Europe, as of 22 November 2026)

Scope note: this extends `docs/design/additive.md` §12.6 and `reports/3D printing service APIs for PartCAD.md`. Those
already cover API access, credentials and payment, so this file does not repeat them. Machine-readable specs were
downloaded on 2026-11-22 and inspected locally: Slant 3D, 3DAPI (designer/integrator and print-farm), Craftcloud and
X3D Studios. Anything that comes only from a search-engine snippet, not a page that was fetched, is marked
**(snippet, unverified)**.

## 1. Which services accept G-code or a sliced 3MF as an order input, for which printers, by API or by hand, and on what terms?

### Takeaway
Only **two services open to the public** take a customer-prepared print file and say plainly that it is what gets printed.
**X3D Studios** (Austin, TX) prints a Bambu-sliced `.gcode.3mf` "exactly as exported" on its Bambu H2S/P2S fleet, by
web upload and by a self-serve REST API. **3DAPI** (US + EU network) takes a Bambu Studio/OrcaSlicer **3MF project with
print settings** for Bambu P1S, 0.4 mm. When the project needs changing, 3DAPI writes a "production version" 3MF, and
that, not the upload, is what gets printed. No large bureau or marketplace takes G-code: Xometry, Protolabs Network,
Shapeways, Craftcloud, Treatstock, Slant 3D, JLC3DP and PCBWay all quote a mesh or CAD file and slice it
themselves. G-code intake survives at a few campus libraries, which serve only their own patrons.

### Cited Findings

**X3D Studios (US, Austin TX): sliced plate printed as-is, by web and API**
- Web upload takes STL (≤100 MB, which X3D slices) and 3MF (≤40 MB): "a model, a slicer project, or a sliced plate export". A `.gcode.3mf` is treated as a 3MF, and a plate export "prints exactly as exported". Bare `.gcode`, GLB and OBJ are refused on the web — [X3D docs: file formats](https://x3dstudios.com/docs/file-formats)
- For a sliced plate, layer height, infill, supports, orientation and plate position "are whatever you set", and the site cannot change any of them. For an unsliced *project* 3MF in colour mode, "Its project-wide print settings are not used": it is re-sliced on X3D's standard 0.2 mm profile — [X3D docs: file formats](https://x3dstudios.com/docs/file-formats)
- Printer models: "Slice for a Bambu H2S or P2S. Those are the machines in the fleet." "A file sliced for a different printer model is a hard failure at the farm, not a warning." — [X3D docs: file formats](https://x3dstudios.com/docs/file-formats)
- Reason for the web rule: the farm starts every print from a plate 3MF, so a bare `.gcode` "could be paid for and then never start" (search summary of X3D's docs; the same docs say the API does take `.gcode`) — [X3D docs](https://x3dstudios.com/docs) **(snippet, unverified)**
- API: OpenAPI 3.1 at `https://x3dstudios.com/openapi.json` ("X3D Studios Print API" 1.0.0). `POST /api/print/orders` takes a multipart `file` with extensions ".stl, .glb, .gcode, .3mf (a .gcode.3mf is treated as 3mf)", up to 100 MB. It charges the card on file and returns an order code `X3D-XXXXXX`. There are no webhooks: poll `GET /api/print/orders/{code}`. An MCP endpoint is at `/api/mcp` — [X3D OpenAPI](https://x3dstudios.com/openapi.json); [X3D API docs](https://x3dstudios.com/docs/api)
- Keys are self-serve: add a card at `/profile`, then "Generate key" (`x3d_live_` prefix) — [X3D API docs](https://x3dstudios.com/docs/api)
- Ships to the US ($7 standard) and internationally ($30 flat; express is US-only). Prices in USD only — [X3D OpenAPI](https://x3dstudios.com/openapi.json)
- Terms: "A print that fails on our machine is printed again at our cost." If a part arrives wrong, "a person decides on a reprint or a refund." The page says nothing specific about failures *caused by* a customer-sliced file — [Why X3D](https://x3dstudios.com/why-x3d)
- A sliced plate using five or more filaments carries a $25 "second-AMS" fee — [X3D OpenAPI](https://x3dstudios.com/openapi.json)

**3DAPI / dapi.digital (US + EU production network): 3MF project with print settings, Bambu P1S**
- "Quote `.stl`, `.3mf`, `.obj`, `.step` or `.stp` files of up to 250 MiB… A `.3mf` project is the best choice: it carries your colours, filaments and print settings, which 3DAPI reads to suggest materials." — [3DAPI file requirements](https://public-api.dapi.digital/docs/guides/file-requirements.md)
- "Files are printed on Bambu Lab P1S printers with a 0.4 mm nozzle. In a `.3mf`, include the full print settings: 0.20 mm layer height; P1S printer profile, 0.4 mm nozzle; Supports enabled, on the build plate only. Plain mesh files (`.stl`, `.obj`, `.step`) are sliced with these settings." — [3DAPI file requirements](https://public-api.dapi.digital/docs/guides/file-requirements.md)
- Up to 4 colours (filament slots) per file. The geometry has to be manifold, have no wall thinner than 0.45 mm, have a flat bottom, and fit the P1S plate — [3DAPI file requirements](https://public-api.dapi.digital/docs/guides/file-requirements.md)
- Terms: after the 10-file onboarding review, "there is no review per file: an order goes to production as soon as its quote is `ready`, so these requirements are yours to keep from then on." — [3DAPI file requirements](https://public-api.dapi.digital/docs/guides/file-requirements.md)
- G-code: the published docs never mention a `.gcode` or `.gcode.3mf` input. The integrator OpenAPI (1.59 MB, inspected) has no `gcode` field — [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)

**Services that do not take G-code or a sliced file**
- Treatstock: "Currently, only STL, PLY and 3MF file formats are supported for manufacturing orders." "For 3MF files, we can only handle 5MB maximum." — [Treatstock help 37](https://www.treatstock.com/help/article/37-what-types-of-files-are-supported-for-3d-printing); [Treatstock help 241](https://www.treatstock.com/help/article/241-why-my-3mf-file-is-declined)
- Slant 3D: the file schema's `type` enum is `["stl"]`, described as "File type - currently only STL supported" — [Slant 3D OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- Craftcloud: every model example in the v5 spec is `testmodel.stl` with `fileUnit` in `mm|cm|in`. The spec has no G-code or slicer-project input — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- Xometry's accepted uploads are "STEP · STP · SLDPRT · STL · DXF · IPT · X_T · X_B · 3DXML · CATPART · PRT · SAT · 3MF · JT", all design formats, with no G-code — [Xometry infill article](https://www.xometry.com/resources/3d-printing/comparing-infill-options-for-fdm-1/)
- JLC3DP's FDM page names only STL uploads for an instant quote — [JLC3DP FDM](https://jlc3dp.com/3d-printing/fused-deposition-modeling)
- Shapeways' upload list is DAE, OBJ, STL, X3D, X3DB, X3DV, WRL, 3MF, STP, STEP — [Shapeways support](https://support.shapeways.com/hc/en-nl/articles/17000648918300-How-to-upload-your-3D-model) **(snippet, unverified)**

**Peer-to-peer and ecosystem marketplaces (Bambu MakerWorld, Printables)**
- No MakerWorld or Bambu Lab service was found that prints and ships for a buyer without a printer. Searches turned up only "send to your own printer" via Bambu Handy — [MakerWorld FAQ](https://makerworld.com/en/faq) **(snippet, unverified)**. The Commercial License Membership lets *makers* buy a licence to sell physical prints of a creator's model — [All3DP](https://all3dp.com/4/bambu-lab-launches-makerworld-commercial-license-membership/) **(snippet, unverified)**
- MakerWorld itself refuses G-code: its upload page says "Only 3MF files produced by Bambu Studio are supported." A community member gives the reason as "To prevent users running gcode generated for printer X on printer Y and damaging hardware" (thread of 26 Feb 2024, no official answer) — [Bambu forum](https://forum.bambulab.com/t/why-cant-i-upload-gcode/61600)
- Printables "offers not only STL files but also G-Codes for the Original Prusa printers": G-code for people to print on their *own* Prusa machines, not a print service — [Prusa help](https://help.prusa3d.com/article/customer-support_2287) **(snippet, unverified)**
- Prusa Research sells farms (Prusa Farm, the AFS automated farm: "upload a file and start printing") rather than printing for hire. No Prusa print-for-hire offer was found — [Prusa Farm](https://www.prusa3d.com/p/prusa-farm); [Prusa Pro AFS](https://afs.prusa3d.com) **(snippet, unverified)**
- Shapeways' Thangs print-on-demand lets Thangs creators sell designs that Shapeways prints and ships. It is mesh-based and offers no settings — [Shapeways blog](https://www.shapeways.com/blog/thangs-self-service-print-on-demand-is-live-powered-by-shapeways) **(snippet, unverified)**

**Farm software and the de facto "print-ready" container (context, not order services)**
- Bambu Farm Manager: "Use Bambu Studio to 'Export plate sliced file' and upload the gcode.3mf file to Farm Manager (currently only single-plate is supported)" — [Bambu wiki](https://wiki.bambulab.com/en/software/bambu-farm-manager) **(snippet, unverified)**
- FarmLoop Processing API (3D Farmers) accepts `.gcode.3mf`, `.3mf` *with* G-code, `.gcode` and `.bgcode`. "Not accepted: project files without gcode." "All files must be sliced for the same printer model." It names P1S, X1E and H2D, and a Business plan is required — [FarmLoop Processing API](https://help.3d-farmers.com/integrations/processing-api/)
- Printago accepts "pre-sliced .gcode.3mf files directly" for teams wanting control of the artifact — [Printago](https://printago.io/features/bambu-studio) **(snippet, unverified)**. SimplyPrint: a sliced `.gcode.3mf` prints as-is on Bambu printers — [SimplyPrint help](https://help.simplyprint.io/en/article/uploading-files-and-splitting-multi-plate-3mf-files-1dpbgrz/) **(snippet, unverified)**

**University / library remote print services**
- Alabama State University library (Levi Watkins Learning Center): ".STL or .GCODE only (no ZIP archives)", printed on a Fusion3 F410, with a maximum print time of 2 hours. "The LWLC is not responsible for design errors." Patrons prepare their own files and staff do not modify designs — [ASU 3D guidelines](https://lib.alasu.edu/3d/3dguidelines.html)
- Penn State Maker Commons takes submissions "through the 3DPrinterOS Cloud Slicing software", framed for "Penn State students and faculty", with print credits — [PSU FAQ](https://makercommons.psu.edu/3d-printing-faq). Its tutorial has users submit a ".gcode (Prusa_MK4S)" file — [PSU](https://makercommons.psu.edu/?p=4869) **(snippet, unverified)**
- Georgia Southern libraries: "We will not accept .gcode files that were prepared by someone else." Staff evaluate the model and "convert it to a .gcode file" themselves — [Georgia Southern LibGuide](https://georgiasouthern.libguides.com/3dprinting)
- University of Florida (STL/3MF, sliced in-house in PrusaSlicer) and University of Utah (remote jobs on a Prusa MK3, white PLA only) slice in-house — [UF](https://makerspace.uflib.ufl.edu/3dprocess/); [Utah](https://lib.utah.edu/protospace/3D.php) **(snippets, unverified)**

### Inferences
- X3D Studios is the only service found where "the validated print is the delivered print" holds by contract wording ("prints exactly as exported"). The file has to be a Bambu `.gcode.3mf` plate for an H2S or P2S. PartCAD's `pc cam` today writes plain G-code, from its own FFF route writer or from PrusaSlicer. So reaching X3D needs either a Bambu-format plate container for an H2S/P2S profile, or a test of whether the API's `.gcode` path really prints a bare file. The web docs and the API spec disagree on bare `.gcode`.
- 3DAPI is "print exactly this *project*", not "exactly this *route*": it re-slices a project on its own printers, under its own fixed constraints (P1S, 0.4 mm, 0.20 mm, supports on the plate only). What can carry over from PartCAD's `fff:` is the values Bambu Studio keeps in the project: walls, top/bottom layers, infill % and pattern, and orientation through the plate placement. That carry-over is **unverified**: the docs do not list which settings 3DAPI's check rewrites.
- Both route-honouring services are Bambu-only, single-vendor fleets, which is why they can honour a slice: a fleet of one printer model has one machine profile to validate against. A marketplace of mixed machines (Craftcloud, Treatstock) cannot.
- No terms anywhere assign the cost of a failed print *caused by* a customer's own slice. X3D's reprint promise is generic, and 3DAPI puts the requirements on the integrator after approval. A PartCAD plugin should assume the cost of a bad route falls on the user.

### Gaps
- I did not verify that X3D's API prints a bare `.gcode` file. The spec accepts the extension, while the web docs say the farm needs a plate 3MF.
- I found no X3D terms that address who pays when a customer's slice fails (for example, a slice for the wrong printer). The farm calls that case a "hard failure" but does not state the refund consequence.
- 3DAPI's docs do not say which settings in an uploaded project are kept and which are overwritten when it prepares a `production_version`.
- I found no European counterpart to X3D, a public farm that prints a customer `.gcode.3mf` as-is; a German-language search found none. 3DPrintsToronto (Canada, outside scope) runs a multi-plate `.gcode.3mf` order flow — [3DPrintsToronto blog](https://3dprintstoronto.com/blog/multi-plate-3mf-order) **(snippet, unverified)**.
- Weerg and Materialise OnSite were not re-checked in this pass. Neither is known to offer FDM settings, and Weerg's `llms.txt` points agents to its configurator (see the earlier report).
- The GoodPrints3D/JC Print Farm guide (19 Apr 2026) says a supplier "should restate… any settings it plans to change" but gives no policy of its own — [GoodPrints3D](https://www.goodprints3d.com/blogs/3d/should-you-send-a-3mf-file-for-a-custom-3d-printing-quote).

## 2. Which services accept explicit process settings as order options (API or web), and which settings?

### Takeaway
Settings offered as order options are few and coarse. Infill is the setting most often offered, as **grades or a fixed
menu** (Xometry three grades, Protolabs Network 20–80 % or three grades, Craftcloud per-vendor `infill_40…100`). Layer
height is sometimes a three-step quality choice. **X3D Studios' API is the only one found with numeric `infill` %
and `layerHeight` mm plus `nozzleDiameter`**. **No service takes walls/perimeters, top/bottom layers, infill pattern or
build orientation as a structured field**; orientation and supports go only into free-text notes (Craftcloud,
X3D). A specific **filament brand/colour** can be chosen at Slant 3D (`filamentId`, whose `provider` is the filament
manufacturer), at 3DAPI (catalog material per extruder slot) and at X3D (stock spool name or hex).

### Cited Findings

**X3D Studios API: the most complete settings set found**
- `POST /api/print/orders` fields: `material` (pla, petg, abs, asa, tpu); `color` (stock spool name or hex, free text billed at a custom-colour floor); `quality` (standard or premium, "Sets the price factor only… It does not change the layer height on this endpoint"); `layerHeight` ("Millimetres. Clamped, never rejected, to 20 to 75% of the nozzle diameter: 0.08 to 0.30 mm on a 0.4 mm nozzle"); `infill` ("Percent. Clamped to 10 to 100, never rejected. Ignored for an already-sliced file, which is recorded as 100 because the slice already decided."); `nozzleDiameter` (0.2/0.4/0.6/0.8, "Any other value falls back to 0.4 silently"); `nozzleFlow` (standard or high); `note` ("Free text for the operator: orientation, support preferences, anything a human should read before printing. Truncated to 1000 characters without warning.") — [X3D OpenAPI](https://x3dstudios.com/openapi.json)
- No field exists for walls, top/bottom layers, infill pattern, orientation or printer model — [X3D OpenAPI](https://x3dstudios.com/openapi.json)

**Craftcloud: infill and tolerance as per-vendor priced options, plus a note**
- Quote `options[].types` enum: `economy`, `expedited`, `infill_40`, `infill_60`, `infill_80`, `infill_95`, `infill_100`, `tolerance_004`, `tolerance_003`, `tolerance_002`, `tolerance_001`, `tolerance_tighter_001`. Each option is priced and timed per vendor. The spec's example shows vendor `baysingers` offering `infill_80` at $28.00 and `infill_95` at $30.64 against a $12.00 base — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- A cart quote takes `types` (the applied options) and a `note` (`maxLength` 1024). Models carry an `attachments` array — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- The spec has no layer height, wall, pattern or orientation fields — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)

**Xometry (web only)**
- Infill is chosen under "Material Options" as Ultralight ("a single zig-zag pattern"), Light ("a double cross-hatch pattern") or Solid ("completely filled"). The page gives no percentages — [Xometry](https://www.xometry.com/resources/3d-printing/comparing-infill-options-for-fdm-1/)
- Xometry Europe lists layer thickness as 100 µm (Fine), 200 µm (Standard) and 300 µm (Economy), and infill as ultralight (up to 20 %), light (20–50 %) and solid (50–80 %). The US FDM page instead gives ".007" - .010" layers dependent on material" for parts under 16 in. — [Xometry EU FDM](https://xometry.eu/en/?p=2597); [Xometry FDM](https://www.xometry.com/fused-deposition-modeling-fdm/) **(snippets, unverified: the EU page returned 403 when fetched)**

**Protolabs Network (Hubs) (web only)**
- Layer height "100-300 μm" (100–330 μm for industrial FDM). Infill "20-80%" for prototyping FDM and "Ultra-light, Light, Solid" for industrial FDM (Markforged Onyx, ULTEM 9085/1010, Stratasys ASA, ABS M30). The page offers no printer, colour or orientation choice — [Protolabs Network FDM](https://www.hubs.com/3d-printing/fdm/)

**Slant 3D API: filament choice only**
- Order items take `type: PRINT`, `publicFileServiceId`, `filamentId` and `quantity`. The schema has no layer, infill, wall or orientation fields. `Order.options` is an undocumented nullable object — [Slant 3D OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- `Filament` has `provider` ("Filament manufacturer"), `profile` (`OPM`, `PLA`, `PETG`; "Filaments with any other material type are not exposed on the public API"), `color`, `hexValue` and `available`. So a buyer picks a *specific manufacturer's spool and colour* — [Slant 3D OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- Supports: "`supportRequired`… Internally decided at upload or at time of print". The estimate notes: "Support is determined at the time of upload, not on this request" — [Slant 3D OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- Metrics `z`: "z axis in millimeters. This is the internal vertical direction while printing". This suggests the upload's Z is the build axis, but the spec does not promise that Slant keeps the orientation — [Slant 3D OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- Aside: `POST /files/openScad` turns OpenSCAD source into STL ("100 generations per hour"). It is the only code-CAD input on any service API found — [Slant 3D OpenAPI](https://slant3dapi.com/v2/api/openapi.json)

**3DAPI: settings travel inside the 3MF; materials per extruder slot**
- 3DAPI has no settings fields: the settings are whatever the uploaded `.3mf` holds, within the fixed P1S/0.4/0.20 mm/supports-on-plate constraints — [3DAPI file requirements](https://public-api.dapi.digital/docs/guides/file-requirements.md)
- `suggested_materials[]`: one catalog material per extruder slot, read from the file's colours and filament types (`file_color`, `file_filament_type` such as `PLA` or `PETG-HF`, with `match` `exact`, `close` or `approximate`). Order with `use_suggested_materials: true` or send `materials: [{slot, material}]`. "The print farm loads the material into this slot." — [3DAPI quotes](https://public-api.dapi.digital/docs/reference/quotes.md)
- The catalog material has `name` (for example "PLA Black"), `technology` (`fdm`, "the only one offered today"), `color`, `color_hex` and `filament_type`. It has **no brand field**. "Custom materials need manual review before production." — [3DAPI materials](https://public-api.dapi.digital/docs/reference/materials.md)
- On the farm side, a design carries free-text `farm_instructions` (example: "Print at 0.2mm layer height. Brim recommended.") and a `grams_multiplier` — [3DAPI print-farm OpenAPI](https://public-api.dapi.digital/docs/print-farm.openapi.json)

**Others**
- JLC3DP's FDM page names materials and a recommended 1.2 mm wall thickness (a design guideline), with no layer, infill or remark options — [JLC3DP FDM](https://jlc3dp.com/3d-printing/fused-deposition-modeling). A search summary attributes a "50% infill on all the FDM plastics except TPU… 15%" default, "other values are supported", to JLCPCB — **(snippet, unverified; source page not identified)**
- PCBWay lists FDM materials (PLA, PETG, ABS, Stratasys ABS-ESD7, PA6-CF/GF, PEEK…), "over 50 3D printing machines in our distributed network", a "Custom" material option and an "expert engineering review". The page shows no settings fields — [PCBWay 3D printing](https://www.pcbway.com/rapid-prototyping/3D-Printing/)
- Shapeways added FDM in Feb 2025: ABS, ASA, PC, PET and PETG, "via our online quoting tool". The article mentions no settings — [3DPrint.com](https://3dprint.com/316615/shapeways-expands-3d-printing-portfolio-with-fdm/)
- Sculpteo FDM: Ultrafuse rPET and PETG ESD. The page says customers "can choose between several options" but does not list them — [Sculpteo FDM material](https://sculpteo.com/en/materials/fdm-material/) **(snippet, unverified)**

### Inferences
- PartCAD's `fff:` maps onto services as follows:
  - **`layerHeight`**: X3D (numeric), Xometry EU and Protolabs Network (menus), 3DAPI (fixed 0.20).
  - **`infill`**: X3D (numeric 10–100), Craftcloud (40/60/80/95/100 where a vendor offers it), Protolabs Network (20–80 % or grades), Xometry (grades).
  - **`nozzle`**: X3D only.
  - **`walls`, `topLayers`, `bottomLayers`, `infillPattern` and `toolAxis`/orientation**: no structured field anywhere. Only the 3DAPI 3MF route can carry them, unverified. X3D sliced plates carry them as part of the slice.
  - **`feed`**: nowhere.
- The line in additive.md §12.6, "None takes a filament as a process setting", still holds for *process* settings. It needs a qualification: Slant 3D does take a *specific manufacturer's filament and colour* as an order input (`filamentId` → `provider`), and 3DAPI and X3D map a material to each extruder slot of the file.
- Craftcloud's coarse `infill_*` options mean a PartCAD plugin could at least pass `infill` rounded up to the next grade, and put the rest of `fff:` into the 1024-character note. A note is advisory, though, so the result would not be validated.

### Gaps
- I could not check Craftcloud's web configurator or vendor terms to see whether vendors honour the `note`. I also could not confirm which vendors offer `infill_*` options (the spec example shows one).
- Shapeways, Sculpteo, JLC3DP and PCBWay order forms sit behind uploads or logins. I could not confirm whether they offer infill or layer choices.
- Slant 3D's `Order.options` object is undocumented, so its contents are unknown.

## 3. Do any guarantee or report the actual settings used (sliced file back, part weight), so PartCAD can compare the delivered print with its prediction?

### Takeaway
**3DAPI is the only service found that hands back the exact file it will print.** Each quote exposes
`file.production_version`, the 3MF "that gets printed", fixed once the quote is `ready`, or `null` when the
upload is printed as-is. X3D reports billable grams and print hours, but for a sliced file these are the file's own
figures. Slant 3D reports its own estimated weight and print time per uploaded STL. No service found reports the
*measured* weight of the delivered part.

### Cited Findings
- 3DAPI `file.production_version`: "The copy 3DAPI adapted to the production printer (printer, process and filament settings written in)… This is the file that gets printed, and the one `price` is for." It is "Null when your upload is printed as it is… when the check found nothing to change", and "It never changes once the quote is `ready`." `format` is always `3mf`, and a signed `download_url` expires after 15 minutes — [3DAPI quotes](https://public-api.dapi.digital/docs/reference/quotes.md)
- 3DAPI `create_quote`: "3DAPI first checks the file against its production printers and, when needed, prepares a production version with the right printer, process and filament settings… your upload stays downloadable as it is." — [3DAPI quotes](https://public-api.dapi.digital/docs/reference/quotes.md)
- The 3DAPI quote object has no grams or print-time field. Status `processing` means "the file is being sliced to measure material and print time", but only `price` is returned. Shipping tiers use `chargeable_weight_grams` on catalogue variants — [3DAPI quotes](https://public-api.dapi.digital/docs/reference/quotes.md); [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)
- X3D order response `breakdown`: `grams` ("Billable weight, rounded up to the whole gram") and `printHours` ("Estimated machine hours"). For sliced files, "the quote uses the grams and hours recorded in the file". X3D adds a surcharge only for "an already-sliced file whose measured time far exceeds what its weight implies" — [X3D OpenAPI](https://x3dstudios.com/openapi.json); [X3D API docs](https://x3dstudios.com/docs/api)
- X3D `GET /api/print/orders/{code}` returns status, material, colour, quality, quantity, cost and tracking. It returns no slice file, measured weight or settings echo — [X3D OpenAPI](https://x3dstudios.com/openapi.json)
- Slant 3D `File.metrics` has `weight` ("estimated weight in grams"), `printTimeEstimate` (minutes), `volume`, `surfaceArea`, `supportRequired`, `supportVolumeEstimate`, `bodyCount` and `x/y/z`. `File.notes` holds "Production notes from Slant3D team". `POST /files/{id}/estimate` returns `totalMaterial` and `estimatedPrintTime` — [Slant 3D OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- Craftcloud returns model `area`, `volume` and `dimensions`, and order configuration by `GET /v5/order/{orderId}/configuration`. It returns no slice or weight — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- X3D's reprint guarantee covers failures "on our machine". It is not a guarantee that settings match — [Why X3D](https://x3dstudios.com/why-x3d)

### Inferences
- 3DAPI's `production_version` is what PartCAD's validation loop needs. PartCAD would upload a project, fetch `production_version` (or get `null`, meaning printed as uploaded), re-derive the as-printed part from that file, and refuse or warn if it differs from the validated route. This only works if PartCAD can read a Bambu 3MF project's settings, or re-slice it, so it is a new reader, not a G-code comparison.
- Slant's `metrics.weight` and X3D's `grams` let PartCAD compare *its* predicted weight with the *service's* estimate before ordering. That is a useful cross-check, but it is a prediction against a prediction, not a measurement of the delivered part.

### Gaps
- No service publishes a post-print weight, a QC measurement or the G-code actually run. 3DAPI's designer-side QC tickets carry photos, and whether they ever include weights was not checked.
- It is unverified whether 3DAPI's `production_version` is a *sliced* 3MF (with plate G-code and `slice_info` weights) or an unsliced project with settings written in.

## 4. What do professional services say about why they do not accept customer G-code?

### Takeaway
No major bureau publishes its reasons. The reasons on record come from smaller services, libraries and communities.
(1) G-code is bound to one printer model and firmware: X3D calls a mismatch "a hard failure at the farm". (2) It can
damage hardware: MakerWorld community members, and Prusa forum users on malicious "printer torture" G-code. (3)
Service control and quality: libraries evaluate and slice the model themselves. The services that do honour a
customer's slice are single-model Bambu fleets, which validate a slice against the one machine profile they run.

### Cited Findings
- "A file sliced for a different printer model is a hard failure at the farm, not a warning." — [X3D docs: file formats](https://x3dstudios.com/docs/file-formats)
- FarmLoop: "All files must be sliced for the same printer model." — [FarmLoop Processing API](https://help.3d-farmers.com/integrations/processing-api/)
- MakerWorld accepts "Only 3MF files produced by Bambu Studio". Community reasons: "Gcode is not printer-agnostic, and pre-sliced gcode can be different depending on the target printer"; "To prevent users running gcode generated for printer X on printer Y and damaging hardware". Bambu gave no official answer in the thread — [Bambu forum](https://forum.bambulab.com/t/why-cant-i-upload-gcode/61600)
- A Prusa forum thread, "Dont use gcode you didnt slice yourself", warns that third-party G-code is unreliable across firmware and filament and could carry harmful "printer torture" instructions — [Prusa forum](https://forum.prusa3d.com/forum/english-forum-general-discussion-announcements-and-releases/dont-use-gcode-you-didnt-slice-yourself/) **(snippet, unverified)**
- Georgia Southern libraries: "We will not accept .gcode files that were prepared by someone else". Staff "evaluate the print" and then convert it to G-code themselves — [Georgia Southern LibGuide](https://georgiasouthern.libguides.com/3dprinting)
- 3DAPI keeps the right to adapt any upload to its "production printer (printer, process and filament settings written in)" and prices that version — [3DAPI quotes](https://public-api.dapi.digital/docs/reference/quotes.md)
- Slant 3D decides supports internally ("Internally decided at upload or at time of print") — [Slant 3D OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- The GoodPrints3D guide (19 Apr 2026) says a saved 3MF can hold layer height, walls, infill, temperatures, supports, seams, speeds and machine profiles that "the supplier may review and change" — [GoodPrints3D](https://www.goodprints3d.com/blogs/3d/should-you-send-a-3mf-file-for-a-custom-3d-printing-quote)

### Inferences
- The obstacle is machine identity, not the format. A route is only "as validated" on the machine model, nozzle and firmware it was written for. PartCAD's printer declaration has to name a machine model the service actually runs (Bambu H2S/P2S at X3D, P1S at 3DAPI) for "print it as-is" to mean anything.
- For PartCAD's own route writer to be accepted anywhere, its G-code would have to pass a farm's machine-profile check, which Bambu `.gcode.3mf` metadata expresses. A route written for a generic or Prusa printer has no service to go to; none was found running Prusa fleets for hire.

### Gaps
- No statement of reasons was found from Xometry, Protolabs, Shapeways, Sculpteo, Craftcloud or JLC3DP. The reasons above are inferred from smaller services and from communities.

## 5. Trends: is anyone moving towards "print exactly this project file"?

### Takeaway
Yes, but only inside the Bambu ecosystem, and only at small API-first farms. Bambu's `.gcode.3mf` "plate sliced
file" has become the de facto print-ready container: farm software (Bambu Farm Manager, FarmLoop, Printago,
SimplyPrint) and at least one public service (X3D) take it as-is. 3DAPI builds its intake on Bambu/Orca project
3MFs. Neither Bambu (MakerWorld) nor Prusa (Printables) runs a print-for-you service. Project files do not
travel well between slicer families. The 3MF Consortium's new **Toolpath extension v1.0** (dated 17 Sep 2026) is aimed at
laser powder-bed toolpaths, and no service was found taking 3MF Slice- or Toolpath-extension files for FFF.

### Cited Findings
- 3MF suite as listed on 3mf.io: Core v1.4.0 (ISO/IEC 25422:2025), Slice Extension v1.0.3, Production v1.2.0, **Toolpath Extension v1.0.0 dated 09/17/2026** ("Machine toolpath data for additive processes"), Volumetric v1.0.0 (11/13/2025) — [3mf.io spec](https://3mf.io/spec/)
- Toolpath README: "build-ready toolpath data within 3MF files… model-level toolpath resources, process profiles, per-layer toolpath parts, planar and multi-axis geometry, laser-source metadata". The GitHub repository description reads "Draft for 3MF's lasertoolpath extension specification" — [3MFConsortium/spec_toolpath](https://github.com/3MFConsortium/spec_toolpath)
- All3DP frames the release as letting manufacturers "share and validate laser instructions for powder bed fusion machines" — [All3DP](https://all3dp.com/6/3mf-consortium-releases-open-toolpath-extension-to-improve-metal-3d-printing-interoperability/) **(snippet, unverified: page returned 403)**
- Cross-slicer portability: PrusaSlicer opens Bambu 3MFs with "only the geometry info", because Bambu "uses extensions to supply additional info that is not part of the core 3MF standard". PrusaSlicer's "Import Config from Project" accepts only PrusaSlicer-saved projects. A Bambu forum user reports that Orca→Bambu imports leave "Quality, Strength and so on… not set" — [Prusa forum](https://forum.prusa3d.com/forum/general-software-discussion/3mf-files-from-bambu-studio?language=de); [Bambu forum](https://forum.bambulab.com/t/can-we-upload-ocra-3mf-for-a-print-profile-on-mw/78479) **(snippets, unverified)**
- MakerWorld print profiles are Bambu Studio 3MF projects, each carrying its own layout, orientation and target printer — [MakerWorld FAQ](https://makerworld.com/en/faq) **(snippet, unverified)**
- Agent-facing intake is spreading among the services that do take settings or files: X3D (`/api/mcp`), 3DAPI (`@dapi-digital/mcp`) and Slant 3D (MCP server, per the earlier report) — [X3D OpenAPI](https://x3dstudios.com/openapi.json); [3DAPI llms.txt](https://public-api.dapi.digital/docs/llms.txt)
- 3DAPI's guidance treats the project as the carrier of intent: "A `.3mf` project is the best choice: it carries your colours, filaments and print settings" — [3DAPI file requirements](https://public-api.dapi.digital/docs/guides/file-requirements.md)

### Inferences
- For PartCAD the practical target is not G-code in general but **a Bambu-dialect 3MF**: a sliced `.gcode.3mf` plate for X3D (H2S/P2S), or a project with process settings for 3DAPI (P1S). PrusaSlicer's 3MF is not read with its settings by Bambu-based services, and no PrusaSlicer-fleet service was found. So PartCAD's "unmodified PrusaSlicer run" route would reach no service as-is. An OrcaSlicer or Bambu Studio route would.
- The 3MF Slice and Toolpath extensions are not a near-term path to print services for FFF. Neither is used by any service found, and Toolpath's first target is laser PBF.

### Gaps
- No 2024–2026 trade-press coverage was found of a mainstream bureau moving to "print exactly this project file". The trend evidence is from small farms' own docs.
- Not checked: whether Bambu Studio's newer releases import PrusaSlicer project settings. Also not checked: whether OrcaSlicer's `.gcode.3mf` from a non-Bambu machine profile is accepted by X3D's validation.
