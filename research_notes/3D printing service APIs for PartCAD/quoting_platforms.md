# Instant-quoting / order-management platforms used by independent 3D printing (and CNC) bureaus, and their APIs (as of late 2026)

Scope note: this covers the white-label "shop software" that bureaus run their own online quoting shops on (DigiFabster, 3YOURMIND, AMFG, Paperless Parts, Materialise OnSite/CO-AM, Authentise, etc.), farm-management tools (Printago, 3DPrinterOS, AstroPrint), and vendor-neutral RFQ standards. Marketplaces that sell under their own brand (Xometry, Protolabs Network/Hubs, Fictiv, RapidDirect) are out of scope and covered elsewhere. PartCAD's needs, for reference: `caps` (materials/colours/finishes/formats), `quote` (cart of STEP/STL parts + shipping address -> total price, ISO 4217 currency, cart id), `order` (cart id), with each end user using their own credentials, and ideally one plugin parameterised by a bureau's URL/tenant.

## Q1. Does each platform publish an API, and is it customer-facing (submit model -> price -> order) or only internal/ERP-facing? Docs, protocol, auth, per-tenant, can an end customer get a key?

### Takeaway
Only two platforms have documented APIs that cover upload -> price -> quotation -> order the way PartCAD's `quote`/`order` do: **3YOURMIND** (a REST API on every tenant at `<tenant>/apidocs/`, with "getting prices for 3D models" and "placing orders" as documented use cases, needing a token from the platform owner or 3YOURMIND support) and **Materialise OnSite** (REST at `api.onsite.materialise.com/v1`, client-ID/secret auth, with models, products/price, quotations, addresses and `/order` endpoints). **Paperless Parts** has a well-documented public REST API, but it is ERP-facing: the shop reads its own sent quotes and orders. **DigiFabster** and **AMFG** advertise APIs, but I found no public reference docs. **Authentise** has old public REST docs (3DIAX) and now sells mainly as a workflow/MES integrator (Flows). Printago, 3DPrinterOS and AstroPrint are farm-operations APIs with no quoting. No platform I found documents a self-serve key that a bureau's *end customer* can issue for themselves.

### Cited Findings

**3YOURMIND (Berlin; white-label order portal / "Distributed Manufacturing" platform)**
- 3YOURMIND documents a RESTful API in its Confluence. To find a platform's API reference, "append the /apidocs/ endpoint to the site URL", e.g. `order.yoursite.com/apidocs/`. So the API is served **per tenant, on the bureau's own domain** — [3YOURMIND Confluence: API Use Cases](https://3yourmind.atlassian.net/wiki/x/DYCYdg) (seen as a search snippet; a direct fetch returned an empty page because the page renders with JavaScript)
- The documented use cases are: uploading files programmatically and redirecting users to the frontend; placing orders from another system; ordering from a catalogue item; **getting prices for 3D models**; analysing/optimising models; and pushing request/quote/order data to CRM/ERP/accounting — [3YOURMIND Confluence: API Use Cases](https://3yourmind.atlassian.net/wiki/x/DYCYdg) (search snippet)
- Access: the token's user needs a profile with the right permissions for each action, and "customers without admin panel access must contact 3YOURMIND support to get a token" — [3YOURMIND Confluence: API Use Cases](https://3yourmind.atlassian.net/wiki/x/DYCYdg) (search snippet; paraphrased by the search tool)
- The portal's workflow runs Request -> Quote -> Order, with 3D files, production settings and ordering preferences gathered in one basket. Quotes can be exported as PDF. Bureaus work from a "Service Workspace", and platform owners can invite external print suppliers and enable "Force verify user" to stop uncontrolled registration — [3YOURMIND Confluence: Using Requests, Quotes and Orders](https://3yourmind.atlassian.net/wiki/x/jwDZBg); [Inviting External Suppliers](https://3yourmind.atlassian.net/wiki/x/BAAHbg) (search snippets)

**Materialise OnSite (Materialise's online quoting/ordering service for AM)**
- REST API at base URL `https://api.onsite.materialise.com/v1`, with request/response structures in Swagger. Endpoints: `POST API/token` (client ID + client secret -> temporary token); `POST API/models` (upload a 3D model -> modelID); `GET API/models/{id}/status`; `GET API/models/{id}` (dimensions, volume, area); `GET API/technologies` (technology/material/finish IDs); `POST API/products` (model + material -> productID); `POST API/products/{id}/price`; `GET API/products/{id}/services`; `POST API/delivery-address`; `POST API/quotations` (empty quotation); `POST API/quotations/{id}/items`; `POST API/quotations/{id}/addresses`; `GET API/quotations/{id}` (total cost, transport cost, items); `POST API/quotations/{id}/order`; `DELETE` variants — [OnSite Help Center: API endpoints](https://onsite.helpjuice.com/api-endpoints-)
- Prices are returned "in specified currency", but the page names no currencies or file formats — [OnSite Help Center: API endpoints](https://onsite.helpjuice.com/api-endpoints-)
- The help centre also has "API Order flow model" and "Order Submitting Using API" articles. A delivery address "must be created in your OnSite account to receive its ID", which implies the key is tied to an OnSite *account* (a buyer account) — [OnSite Help Center: API connection](https://onsite.helpjuice.com/api-connection); [API Key Parameters](https://onsite.helpjuice.com/api-connection/api-key-parameters)
- Materialise's older i.materialise web APIs (Upload Model, Pricing by Model ID, Materials Catalog, Order Status) use a personal API code in an HTTP header and return XML or JSON — [i.materialise API docs](https://i.materialise.com/api/docs); [Pricing by Model ID API](https://i.materialise.com/api/docs/pricing-by-model-id-api)

**Materialise CO-AM / Link3D / Streamics**
- Materialise bought an option on Link3D in April 2021 and exercised it later that year, for a reported US$33.5M. Link3D's AM MES was folded into the cloud CO-AM platform — [Materialise press release](https://www.materialise.com/en/news/press-releases/acquire-option-to-buy-link3d); [Metal AM](https://www.metal-am.com/?p=83507)
- CO-AM is described as having a connected ecosystem with an app store where third parties build software. I found no public CO-AM API reference, only user documentation — [Materialise CO-AM user documentation](https://help.materialise.com/co-am-user-documentation); [Digital Engineering 24/7](https://www.digitalengineering247.com/article/materialise-exercises-option-to-buy-link3d)
- DigiFabster's white-label quoting/eCommerce portal was integrated with CO-AM (announced 6 Nov 2023): "Integrating DigiFabster's solution into CO-AM closes the gap between front-end and back-end." — [PR Newswire](https://prnewswire.com/news-releases/digifabster-and-materialise-collaborate-to-integrate-e-commerce-and-quoting-solution-into-additive-manufacturing-workflow-301977983.html)

**Paperless Parts (Boston; quoting/ERP-front-end for CNC, sheet metal and AM job shops)**
- "The most common use for this API is sending data about sent quotes or orders into a third-party application" such as an ERP. Auth is an API token "similar to a password" that "will grant your integration access to your Paperless Parts account", created and revoked on the shop's Settings page. Docs are at https://docs.paperlessparts.com/v2, plus a Python SDK (https://github.com/part-os/core-python) and a Streaming API for event-driven integrations — [Paperless Parts API page](https://paperlessparts.com/api)
- The SDK provides "identifying newly sent quotes, pulling all information related to a particular quote, and updating a quote's status", i.e. the shop's side of the workflow — [part-os/core-python](https://github.com/part-os/core-python) (search snippet)
- Third-party API directories list v1 and v2 at `api.paperlessparts.com`, covering quotes, quote items, orders, jobs, parts, processes, contacts and accounts, with routes such as `POST /quotes/public` — [apis.io](https://apis.io/providers/paperless-parts/) (secondhand and unverified; the v2 docs page renders client-side and could not be read)
- The Authentise integration shows the auth shape: a webhook on `Order.Status_Change`, plus an Integration ID, API Key and Signing Secret generated in Paperless Parts by the shop — [Authentise help: Connecting Flows with Paperless Parts](https://www.authentise.com/help-articles/connecting-flows-with-paperless-parts---setting-up-the-integration)

**DigiFabster (white-label instant quoting + eCommerce for AM, CNC, sheet metal, laser)**
- The homepage pitches "Manufacturing Shop Software That Helps You Sell More, Instantly" and "drive sales 24/7 with an eCommerce storefront". A directly fetched copy of the homepage did not mention an API — [digifabster.com](https://digifabster.com)
- Search snippets of DigiFabster pages refer to using its quoting technology "behind your existing systems by using our world-class API". A G2 reviewer says "the fully documented API allows you to utilize the data with other software like ERP, accounting or shipping" — [digifabster.com](https://digifabster.com) (snippet); [G2 review](https://www.g2.com/survey_responses/digifabster-review-4006776)
- An automated "agent-ready" index says DigiFabster's API documentation is gated or absent — [xpay Agent-Ready Index](https://www.xpay.sh/agent-ready-index/digifabster/) (unverified automated scoring)
- The AI Quote Agent (Dec 2024, beta) reads a shop's email inbox, creates a draft order, uploads the CAD model and prices it. It connects through email forwarding, not an API — [TCT Magazine](https://www.tctmagazine.com/digifabster-launches-ai-quote-agent-for-manufacturing-shops/)
- Integrations: Materialise CO-AM (2023), Oqton (partnership), 3DEXPERIENCE Make marketplace, and Authentise Flows (2025): "an accepted quote in Digifabster becomes a production order in Flows" — [PR Newswire](https://prnewswire.com/news-releases/digifabster-and-materialise-collaborate-to-integrate-e-commerce-and-quoting-solution-into-additive-manufacturing-workflow-301977983.html); [Metal AM: Oqton partners with DigiFabster](https://www.metal-am.com/oqton-partners-with-digifabster-for-an-am-e-commerce-solution/); [3DS Make blog](https://www.3ds.com/make/solutions/blog/digifabster-3dexperience-make-announce-their-new-partnership); [Authentise Oct 2025 CEO email](https://www.authentise.com/emails-from-the-ceo-reader/october-2025)

**AMFG (London; AM/CNC MES with an instant-quote portal)**
- AMFG says its "API integrations enable full, bi-directional communication with any external systems", offers APIs for "500+ 3rd party software solutions", and sells "Custom APIs" built by its technical-services team. Named ERP/CRM targets include JobBoss2, Fulcrum, SAP, Odoo, HubSpot, Salesforce and Monday.com — [AMFG integration page](https://www.amfg.ai/integration); [AMFG pricing](https://www.amfg.ai/pricing) (vendor claims, seen via search snippet)
- Its Instant Quoting Portal lets customers "upload a CAD file, set their parameters, and receive an accurate quote ... in seconds" and is embedded in the bureau's website, e.g. BensonsCNC — [AMFG blog: Instant Quote Tool](https://www.amfg.ai/post/amfgs-instant-quote-tool-a-step-forward-in-automation); [BensonsCNC case](https://www.amfg.ai/post/bensonscnc-now-offers-instant-quoting-with-amfgs-tailored-software)
- I found no public API reference. Slashdot's listing says "No Integrations at this time", which contradicts the vendor — [Slashdot](https://slashdot.org/software/p/AMFG)

**Authentise (3DIAX API; Flows MES/workflow)**
- Legacy 3DIAX docs describe open REST APIs per module (e.g. `data.authentise.com`, `users.authentise.com`), "open and available to the general public", with API tokens. The pages date from 2014–2016 — [Authentise 3DIAX docs](https://docs.authentise.com/3diax/overview.html); [API design](https://docs.authentise.com/3diax/api_design.html)
- In 2025 Authentise added Flows integrations with 3D Spark, DigiFabster and Paperless Parts; quotes accepted on those front ends become production orders in Flows — [3DPrint.com](https://3dprint.com/321940/d-embargo-4-pm-eastern-11-6-authentise-expands-its-connected-manufacturing-ecosystem-w-3-new-integrations/amp/); [Authentise software integrations](https://www.authentise.com/solutions/flows/software-integrations)

**Oqton (MOS)**
- Oqton partnered with DigiFabster for AM e-commerce, so the customer-facing quoting front end was DigiFabster's, not Oqton's own — [Metal AM](https://www.metal-am.com/oqton-partners-with-digifabster-for-an-am-e-commerce-solution/)

**Print-farm platforms (no quoting)**
- Printago: a REST API plus realtime MQTT, base `api.printago.io`, header `authorization: ApiKey YOUR_API_KEY`, OpenAPI spec at docs.printago.io. It offers Shopify order fulfilment (SKU -> model -> cloud slicing -> printer) and an MCP server. I found no quoting/pricing endpoint — [Printago blog: 3D print farm API](https://printago.io/blog/3d-print-farm-api); [Printago add-ons](https://www.printago.io/add-ons) (search snippets)
- The API opened Nov 28, 2024 as an alpha, "the same API that powers Printago.io", granted case by case — [Printago blog](https://printago.io/blog/printago-goes-free-forever-opens-api-access-for-developers)
- AstroPrint's developer API lets a third party "inject STL files into AstroPrint users' accounts" — [AstroPrint 3D Print API sample](https://astroprint.github.io/3d-print-api-sample)
- 3DPrinterOS publishes a management API reference and "Global API calls v2.1" (cloud slicing, queues, order info) — [3DPrinterOS API reference](https://3dprinteros.com/de/3d-printing-management-apis-reference); [3DPrinterOS help: Global API calls v2.1](https://intercom.help/3DPrinterOS/en/articles/13516944-3dprinteros-global-api-calls-v2-1)

### Inferences
- **3YOURMIND is the strongest "one plugin, many bureaus" candidate.** Every tenant serves the same product's API at `<tenant-domain>/apidocs/`, and the use cases cover price-a-model and place-an-order. A PartCAD plugin parameterised by tenant URL plus a user token is plausible. Blocker: tokens appear to come from the platform owner or 3YOURMIND support, not self-service, and their permissions are role-dependent. Expect per-bureau onboarding of each user, and confirm against a live `/apidocs/`.
- **Materialise OnSite's API maps almost 1:1 onto PartCAD's calls:** `technologies` -> `caps`; models + products + price + quotations + addresses -> `quote` (total cost + transport); `quotations/{id}/order` -> `order`. OnSite appears to be one Materialise-run service, not a white-label platform for independent bureaus, so it reaches one supplier, not many. That is unconfirmed.
- Paperless Parts, AMFG, CO-AM, Oqton and Authentise expose APIs *to the shop*. A buyer-side PartCAD plugin cannot use them with buyer credentials, even though many bureaus run them.
- DigiFabster has the largest bureau footprint among white-label AM quoting tools by press coverage, but without public docs a plugin would need a partnership. Bureaus hold any API key, so end customers would not get one.

### Gaps
- The live 3YOURMIND `/apidocs/` (endpoint names, auth header, currency field, address handling) could not be read. Confirm on a live tenant.
- Whether an *end customer* of a 3YOURMIND or DigiFabster shop can obtain an API token by any route other than the bureau or support is not documented.
- Paperless Parts' `POST /quotes/public` is listed only by a third-party directory, and its meaning is unverified.
- The OnSite API's supported file formats and currencies are not stated, and neither is whether OnSite tenants exist beyond Materialise itself.
- No public API docs were found for DigiFabster, AMFG or CO-AM.

## Q2. Formats accepted and whether pricing is instant/automatic

### Takeaway
All the white-label quoting platforms advertise instant, automatic pricing from uploaded CAD, falling back to manual review. STEP and STL are universally accepted where formats are stated, and 3MF is named by Paperless Parts.

### Cited Findings
- Paperless Parts supports STEP, STP, STL (and IGES, IGS, SAT, among others), lists 3MF, and covers additive processes (FDM, SLS, SLA, PBF, MJF, binder jetting) — [Paperless Parts llms.txt](https://www.paperlessparts.com/llms.txt)
- The AMFG instant-quote portal accepts "30+ different file types; PDF, STEP, DWG, DXF, and more" and prices from "your shop's own costing logic, in seconds" — [AMFG instant quote blog](https://www.amfg.ai/post/amfgs-instant-quote-tool-a-step-forward-in-automation) (vendor claim, seen via snippet)
- Creabis (Munich bureau on 3YOURMIND) customers get a price and delivery quote instantly instead of waiting four to six hours. 3YOURMIND also has a "Request" stage for manual pricing or advice — [3YOURMIND: Creabis](https://www.3yourmind.com/news/creabis-empowers-customers-to-order-parts-24/7-365); [3YOURMIND Confluence](https://3yourmind.atlassian.net/wiki/x/jwDZBg)
- DigiFabster is "a fully white-labeled eCommerce portal offering a machine learning-driven quoting system" — [PR Newswire](https://prnewswire.com/news-releases/digifabster-and-materialise-collaborate-to-integrate-e-commerce-and-quoting-solution-into-additive-manufacturing-workflow-301977983.html)
- The Catena-X RFQ standard's examples carry STEP CAD plus PDF attachments — [CX-0129](https://catenax-ev.github.io/docs/next/standards/CX-0129-RequestforQuotationExchange)

### Inferences
- Sending STEP (PartCAD's default) is safe on every platform. STL is accepted for AM.
- On all these platforms "instant" is per bureau configuration. Bureaus can route a part to manual quoting, so a plugin's `quote` must handle a "no automatic price" (pending/RFQ) outcome.

### Gaps
- No primary DigiFabster or 3YOURMIND file-format list was retrieved.
- OnSite formats are not stated.

## Q3. How many bureaus use each platform, notable US/EU bureaus, and are their shops discoverable?

### Takeaway
Hard numbers are scarce. Paperless Parts claims 800+ manufacturers, mostly US machine shops. 3YOURMIND and DigiFabster cite named European/US bureaus in case studies but publish no counts. No platform publishes a directory of tenant shops, so discovery would need curation by hand (e.g., in PartCAD's public index).

### Cited Findings
- Paperless Parts: "800+ custom part manufacturing businesses served". It is Boston-based, with US-hosted infrastructure and US-based support — [Paperless Parts llms.txt](https://www.paperlessparts.com/llms.txt)
- 3YOURMIND customers named: Creabis (Munich bureau, web shop), 3D Center (Swedish HP MJF distributor's B2B platform), PostNord, TÜV SÜD, CIPRES, Technology Applied — [3YOURMIND: Creabis](https://www.3yourmind.com/news/creabis-empowers-customers-to-order-parts-24/7-365); [DE247: 3D Center](https://www.digitalengineering247.com/article/3d-center-launches-3d-printing-platform-via-collaboration-with-3yourmind/Additive-Manufacturing); [casestudies.com: PostNord](https://www.casestudies.com/company/3yourmind/case-study/on-demand-am-expertise-for-customers-and-employees)
- DigiFabster case studies: 3DPeople (UK), CubicInch, 3DK Factory, and ZiggZagg (Belgium; "$1M+ in first-year sales") — [digifabster.com/cases/3dpeople](https://digifabster.com/cases/3dpeople/); [cases/cubicinch](https://digifabster.com/cases/cubicinch); [cases/3dkfactory](https://digifabster.com/cases/3dkfactory/); [casestudies.com: ZiggZagg](https://www.casestudies.com/company/digifabster/case-study/ziggzagg-increased-sales-for-over-1m-usd-in-first-year-with-digifabster)
- AMFG customers named: Stack3d (July 2025), A3D Manufacturing (Sept 2025), AME-3D, BensonsCNC — [AMFG: Stack3d](https://www.amfg.ai/post/stack3d-upgrades-their-quoting-speeds-with-amfgs-award-winning-mes-software); [AMFG: A3D](https://www.amfg.ai/customers/a3d-manufacturing); [Metal AM: AME-3D](https://www.metal-am.com/ame-3d-selects-amfg-software-to-streamline-3d-printing-production/)
- DigiFabster funding is small per CB Insights ("$30K over 3 rounds", founded 2014, Irvine HQ). It originated with 3DPrintus — [CB Insights](https://www.cbinsights.com/company/digifabster); [3DPrint.com](https://3dprint.com/90893/digifabster-crm-production/) (aggregator data, unverified)

### Inferences
- Bureaus run these portals on their own domains or subdomains (3YOURMIND's example is `order.yoursite.com`). A "registry of bureaus on platform X" would have to be maintained by hand, which fits PartCAD's public-index model: one entry per bureau with platform + tenant URL.
- 3YOURMIND and DigiFabster skew European (Germany, UK, Benelux). Paperless Parts skews US CNC.

### Gaps
- No tenant counts were found for 3YOURMIND, DigiFabster, AMFG or Materialise OnSite.
- No technical fingerprint (e.g., a footer string or `/apidocs/`) was confirmed for discovering 3YOURMIND/DigiFabster shops automatically.

## Q4. Company status 2024–2026 (acquisitions, shutdowns, retired products)

### Takeaway
The market consolidated and shrank. CASTOR closed (Nov 2025). Shapeways' software (OTTO, MFG, MakerOS lineage) was sold to a management-owned spin-out (May 2024) before Shapeways' bankruptcy. 3D Systems sold Oqton MOS and 3DXpert to Hubb Global Holdings (closed Oct 31, 2025). Link3D lives on inside Materialise CO-AM. DigiFabster, 3YOURMIND, AMFG, Paperless Parts, Authentise and Printago appear independent and active. **DigiFabster is not part of Xometry**: no evidence of any acquisition was found.

### Cited Findings
- DigiFabster: no acquisition found. It was active in Nov 2025 (Authentise integration) — [3DPrint.com](https://3dprint.com/321940/d-embargo-4-pm-eastern-11-6-authentise-expands-its-connected-manufacturing-ecosystem-w-3-new-integrations/amp/); [CB Insights](https://www.cbinsights.com/company/digifabster)
- 3YOURMIND: no insolvency or acquisition found. CB Insights shows a June 2025 accelerator round (EUDIS Business Accelerator), and funding totals conflict between aggregators ($31.01M vs $73K) — [CB Insights](https://www.cbinsights.com/company/3yourmind/financials); [VCBacked](https://www.vcbacked.co/company/3yourmind)
- AMFG: no acquisition. It announced new customer partnerships in 2025 — [Metal AM](https://www.metal-am.com/ame-3d-selects-amfg-software-to-streamline-3d-printing-production/); [AMFG: Stack3d](https://www.amfg.ai/post/stack3d-upgrades-their-quoting-speeds-with-amfgs-award-winning-mes-software)
- Oqton: 3D Systems announced the divestiture of Oqton MOS and 3DXpert in Sept 2025 to Hubb Global Holdings and completed it Oct 31, 2025 for $3.3M cash plus a royalty receivable (PV $7.1M). Oqton had been acquired in 2021 for ~$180M — [3D Systems FY2025 10-K](https://www.sec.gov/Archives/edgar/data/910638/000162828026015997/ddd-20251231.htm); [TCT Magazine](https://www.tctmagazine.com/3d-systems-to-divest-oqton-3dxpert-software-platforms/)
- Shapeways: in May 2024 it agreed to sell its software business (OTTO and MFG, but not InShape) to OTTO dms, Inc., owned by CEO Greg Kress and Greg Rothman. Shapeways then filed for bankruptcy and its executives resigned. Its Dutch arm became Manuevo. Shapeways was later relaunched with all assets except the software — [Fabbaloo](https://www.fabbaloo.com/news/shapeways-to-sell-software-assets-major-shift-in-company-strategy); [3DPrint.com: bankruptcy](https://3dprint.com/311136/shapeways-executives-resign-as-3d-printing-service-files-for-bankruptcy/); [3DPrint.com: Manuevo](https://3dprint.com/311923/european-arm-of-shapeways-saved-by-dutch-senior-management/); [3DPrint.com: relaunch](https://3dprint.com/314952/shapeways-relaunched-with-all-assets-under-one-roof/)
- OTTO launched as SaaS in Oct 2021 (historical) — [TCT Magazine](https://www.tctmagazine.com/shapeways-launches-otto-software-as-a-service/)
- MakerOS (bureau/makerspace business OS, Detroit) was acquired by Shapeways in 2022 per CB Insights (aggregator; exact date unverified) — [CB Insights](https://www.cbinsights.com/company/makeros)
- CASTOR (AM part-identification and cost-estimation software, not a storefront) ceased operations, confirmed by its founder (reports from Nov 2025). Hexagon/Siemens product pages still list it — [TCT Magazine](https://www.tctmagazine.com/castor-ceases-operations-founder-confirms/); [3DPrint.com](https://3dprint.com/319042/israeli-3d-printing-software-startup-castor-files-for-liquidation/); [Siemens CASTOR Enterprise](https://www.siemens.com/de-de/products/castor-enterprise/)
- Link3D: acquired by Materialise in 2021 and folded into CO-AM — [Metal AM](https://www.metal-am.com/?p=83507)
- AstroPrint: said to have been part of Print&Go since Sept 2024 — [Printago comparison page](https://printago.io/alternatives/astroprint) (competitor-authored, unverified)
- Printago: went "free forever" and opened an API alpha in Nov 2024. It is active in 2026 (Shopify integration post, March 2026) — [Printago blog](https://printago.io/blog/printago-goes-free-forever-opens-api-access-for-developers); [Printago blog index](https://www.printago.io/blog)

### Inferences
- Treat OTTO/MakerOS as historical for PartCAD purposes. Their current product status under OTTO dms is unknown.
- Siemens' and Hexagon's CASTOR listings may mean the IP lives on inside those vendors, but CASTOR is a design-for-AM analysis tool, not a bureau storefront, so it is irrelevant to `quote`/`order` anyway.

### Gaps
- Nothing reliable was found on **Cuttr, Kanfit, Fabrikado, "Karmak"/Quotemachining-type tools**. Searches returned no matching quoting products (Karmak is known as a truck-dealer DMS, so the name may be a mix-up). "Partful" surfaced only as an unrelated consumer invitation app. These need direct vendor checks before any claim is made.
- Current status and URL of OTTO dms are unknown.
- Whether Hubb Global Holdings keeps Oqton MOS's DigiFabster integration is unknown.

## Q5. Open standards for a vendor-neutral "quote this part" request, and their maturity

### Takeaway
The only concrete vendor-neutral RFQ standard found is **Catena-X CX-0129 "Request for Quotation Exchange"** (v2.0.1, in the CX-Neptune *preview* release). It is a JSON/SAMM aspect model with AAS artefacts, sent buyer -> supplier over HTTPS through an Eclipse Dataspace Connector, and it explicitly **excludes the offer/price response**. It also needs Catena-X onboarding and a BPN identity, so it is far from a lightweight "quote this STEP" API. OPC UA for AM (OPC 40540, v1.0.0, Feb 2025) is a machine-level information model, not commerce. Manufacturing-X / Factory-X MaaS work is research-stage.

### Cited Findings
- CX-0129 v2.0.1 is listed as "unreleased documentation for Catena-X - Library CX-Neptune (Preview)". Its aspect model is `urn:samm:io.catenax.request_for_quotation:3.0.0`, plus `urn:samm:io.catenax.shared.bill_of_process:1.1.0`. The example payload includes a STEP CAD file and PDF, material family and properties, general tolerance (ISO 2768-1), part/order quantities, delivery dates and manufacturing domain. Transport is a synchronous HTTPS POST of JSON (max 15 MiB) via a CX-0018 connector (Tractus-X EDC), answered with `201 Created`. Offers and later steps "are not in the scope of the standard". Parties must be onboarded (CX-0006) and identified by BPN (CX-0010). It targets Manufacturing-as-a-Service, including on-demand manufacturing (ODM) platforms — [Catena-X CX-0129](https://catenax-ev.github.io/docs/next/standards/CX-0129-RequestforQuotationExchange)
- A companion Catena-X standard covers capacity: CX-0128 Demand and Capacity Management — [CX-0128](https://catenax-ev.github.io/docs/standards/CX-0128-DemandandCapacityManagementDataExchange)
- An academic Catena-X MaaS paper identifies a Request for Quotation API and a Manufacturing Capability API as the two domain APIs — [PMC10490677](https://ncbi.nlm.nih.gov/pmc/articles/PMC10490677)
- Factory-X (Manufacturing-X) MaaS: capability-based matchmaking, then the RFQ is submitted "in a structured AAS format to the supplier via the supplier's connectivity or UI application" — [arXiv 2604.03678](https://arxiv.org/pdf/2604.03678)
- The Manufacturing-X Asset Data Modelling Guideline (IDTA, May 2026) covers AAS submodel instantiation (on-demand vs pre-staged) — [IDTA/Manufacturing-X guideline](https://industrialdigitaltwin.org/wp-content/uploads/2026/05/Manufacturing-X_Asset-Data-Modelling-Guideline.pdf)
- Catena-X and the OPC Foundation published a joint integration-architecture whitepaper (Aug 2025) — [Catena-X/OPCF whitepaper](https://catena-x.net/wp-content/uploads/2025/08/OPCF-Catena-X-Architecture-Whitepaper-v1.0.pdf)
- OPC 40540 / VDMA 40540 "OPC UA for Additive Manufacturing", v1.0.0, published 2025-02-01, defines an information model for AM machines (ISO/ASTM 52900) for connecting to MES/SCADA/ERP. It has no quoting or ordering — [OPC Foundation reference](https://reference.opcfoundation.org/specs/OPC-40540/1); [OPC Foundation document](https://opcfoundation.org/developer-tools/documents/view/332)

### Inferences
- No mature, lightweight, vendor-neutral "quote this part, get price + currency" protocol exists. CX-0129 covers only the request half and assumes a dataspace stack (EDC, BPN, onboarding), which an individual PartCAD user cannot easily join.
- CX-0129's RFQ fields (CAD file, material, tolerance, quantities, delivery date) are still a good reference vocabulary for PartCAD's own `quote` request schema. Aligning field names would ease a future bridge to Catena-X/Factory-X.
- PartCAD's plugin interface (`caps`/`quote`/`order`) is itself a candidate open shape. Nothing in the market fills that niche.

### Gaps
- I found no evidence of any of the commercial quoting platforms (3YOURMIND, DigiFabster, AMFG, Paperless Parts) implementing CX-0129.
- No other RFQ JSON standard was found (e.g., from ASTM, ISO TC261 or the MTConnect community). This may need a dedicated search.
- The Gaia-X-specific manufacturing quote work was not located.
