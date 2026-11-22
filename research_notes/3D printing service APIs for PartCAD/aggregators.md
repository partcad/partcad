# 3D printing marketplaces and aggregators (US/EU): developer APIs as of late 2026

Scope: Craftcloud (All3DP), Treatstock, Shapeways, Hubs / Protolabs Network, Xometry (US + EU), Fictiv, Quickparts, PCBWay, JLC3DP/JLCPCB, plus others with a public API found along the way (i.materialise, Sculpteo). The question behind it: which of these could back a PartCAD `manufacturer` plugin (`caps` / `quote` / `order`, with each user's own credentials).

Method note: primary documentation was fetched where reachable. craftcloud3d.com and api.craftcloud3d.com/ return a Cloudflare 403 to automated fetchers, but the **machine-readable OpenAPI spec at `https://api.craftcloud3d.com/api-docs.json` was downloaded and inspected directly** (2026-11-22), and `GET https://api.craftcloud3d.com/v5/health_check` answered `{"status":"ok"}`. The i.materialise API pages returned 404 to the fetcher, and sculpteo.com returned 403, so the claims about those two rest on search-result snippets and are marked as such.

## Which services have a public, documented API, and where are the docs?

### Takeaway
Only four services in scope have a buyer-side API that is publicly documented and that a third party can use without a negotiated contract: **Craftcloud** (Swagger 2.0 spec published; quote, cart, order and payment endpoints), **Treatstock** (REST API v2 documented in its help centre, plus an official PHP client), **Shapeways** (the legacy REST API with OAuth2, which still answers in 2026 but has no visible maintenance after the relaunch), and **i.materialise** (documented API families, secondhand only). Xometry's public developer API is a **supplier-side** API for manufacturing partners and does not quote or order. JLCPCB has a 3D-printing API behind an approval gate. No public API was found for Fictiv, Quickparts or Protolabs Network/Hubs.

### Cited Findings

**Craftcloud (All3DP GmbH, Munich), primary source: its OpenAPI spec**
- The spec at `https://api.craftcloud3d.com/api-docs.json` is Swagger 2.0, `info: {title: "Craftcloud", version: "v5", description: "Craftcloud API documentation"}`. Its paths include `POST /v5/price`, `GET /v5/price/{priceId}`, `GET /v5/price/{priceId}/grouped`, `POST /v5/cart`, `POST /v5/offer`, `POST /v5/order`, `GET /v5/order/{orderId}/status`, `POST /v5/payment/stripe|paypal|adyen|invoice|quote`, `PATCH /v5/payment/invoice/{paymentId}`, `POST /v5/multi-model-offer`, `POST /v5/vat-validation`, `POST/GET /v5/referral` and `GET /v5/health_check`. Inspected directly — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- A third-party transcription of the Swagger UI (shapeMint repo) also lists `POST /v5/model` (multipart `file`, `unit` mm|cm|in, `refresh`) and `GET /v5/model/{modelId}` (which may return 206 while parsing). It describes the flow as "upload → poll parse → `POST /v5/price` → `GET /v5/price/{id}` → `POST /v5/cart` (quote ids + shipping ids) → `POST /v5/order` → `/v5/payment/...` → `GET /v5/order/{id}/status`". The spec I downloaded does not list `/v5/model` (it may be served by another service or omitted from this spec) — [shapeMint craftcloud_api_merged.md](https://github.com/MattSharp05/shapeMint/blob/HEAD/docs/API_information/craftcloud_api_merged.md)
- Price polling can also be done over WebSocket (`ws(s)://<host>/v5/price/:priceId`, msgpack payloads), which Craftcloud recommends over REST polling — [Kiln blog, 2026-02-18](https://www.kiln3d.com/blog/craftcloud-live); [shapeMint notes](https://github.com/MattSharp05/shapeMint/blob/HEAD/docs/API_information/craftcloud_api_merged.md)
- The spec's `appId` enum is `["craftcloud", "hp", "teleport"]`, "used for tracking purposes", so the same API backs HP's MJF parts portal — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json); [VoxelMatters on HP + Craftcloud](https://www.voxelmatters.com/hp-and-craftcloud-launch-on-demand-mjf-parts-portal-with-instant-quoting/)

**Treatstock (US/EU marketplace)**
- REST API v2 is documented on a help-centre page: `POST /api/v2/printable-packs/` (upload `files[]` or `files-urls[]`, plus `location[country]` or `location[ip]`), `GET /api/v2/printable-packs/<id>`, `PUT` (scale unit, per-part qty), `GET /api/v2/printable-pack-costs/?printablePackId=` (per material/colour/printer prices), `POST /api/v2/place-order/create`, `GET /api/v2/material-group-colors/`. The page carries no publication date, and its sample timestamps are from 2019–2020 — [Treatstock API Documentation](https://www.treatstock.com/help/article/83-api-documentation)
- Official PHP client, last updated February 2022, and a Postman collection — [Treatstock/apiv2 on GitHub](https://github.com/Treatstock/apiv2)

**Shapeways (Eindhoven, NL)**
- The developer portal still lists Materials (list/info), Models (upload/list/info/delete), Orders (place/list/info) and Cart (shipping options). It says "API access is free" and has no notice about the bankruptcy or the relaunch — [developers.shapeways.com](https://developers.shapeways.com/)
- `https://api.shapeways.com/` answered HTTP 200 with a JSON API discovery document whose revision is "20121123". `/materials/v1` answers with a description dated revision "20130228" ("40+ Shapeways' materials"). Probed directly on 2026-11-22 — [api.shapeways.com](https://api.shapeways.com/)

**i.materialise (Materialise, Leuven, BE): secondhand**
- Search snippets describe API families for pricing (including pricing by model id), cart and order status, uploaded-models reporting, order statistics and a materials catalogue; most need an "API code" and a "tool ID" tied to a registered account; a sandbox isolated from printers and payment exists. Pages are undated, and the fetcher got 404s — [i.materialise API docs (snippet)](https://i.materialise.com/api/docs); [Pricing by model id API (snippet)](https://i.materialise.com/api/docs/pricing-by-model-id-api)

**Sculpteo (FR): secondhand**
- The services page says the API automates file upload, instant pricing and order placement, that it is "free for partners" who pay only for printing, and that access and documentation are by contact. The developer docs show "Last update 1970-01-01" (a placeholder) — [Sculpteo API services (snippet)](https://www.sculpteo.com/en/services/api-services/); [Sculpteo webapi docs (snippet)](https://www.sculpteo.com/developer/webapi/)

**Xometry (US; Xometry Europe)**
- `developer.xometry.com` documents accepted jobs, part files, job and line-item statuses (materials received, production started, inspection started) and job-board offers, which need extra approval. You request access by emailing with a "Partner Name" and business email. Quotes and orders are not mentioned — [Xometry Developer API: Getting Started](https://developer.xometry.com/docs/getting-started)
- Keys are generated on Workcenter's "Developer Token" page, and rate limits are per partner (summary of the developer docs via search) — [Xometry developer docs](https://developer.xometry.com/docs)
- Secondhand: production access is limited to "Approved or PIP partners", and others get 403 — [Supergood API report card (unverified)](https://supergood.ai/api-report-card/xometry)

**JLCPCB / JLC3DP (Shenzhen, CN — not US/EU-based)**
- The API overview lists PCB, SMT stencil, a **3D Printing API** ("3D model upload, parsing results, pricing, and order creation and tracking") and Parts. It does not list CNC. Page last updated 10 Nov 2026 — [JLCPCB Online API Access Application](https://jlcpcb.com/help/article/jlcpcb-online-api-available-now)
- The API platform lists the 3D-printing API covering SLA, MJF, SLM, FDM, SLS and WJP, quote to order (search summary of the platform page) — [JLCPCB API Platform](https://api.jlcpcb.com/)

**PCBWay (Hangzhou, CN — not US/EU-based)**
- The API page offers a **PCB** API (quotation, status review, place order, order tracking); the assembly API is "under construction". It is "for partner who have the ability to develop their own websites". You apply by email, and every application is reviewed. 3D printing is not mentioned on the API page — [PCBWay API Cooperation](https://www.pcbway.com/api_cooperation.html)

**Hubs / Protolabs Network, Fictiv, Quickparts**
- Hubs (formerly 3D Hubs) was acquired by Protolabs in January 2021 and renamed Protolabs Network in January 2024. Nothing I found mentions a current public API — [3DPrint.com](https://3dprint.com/281445/upon-protolabs-acquisition-3d-hubs-becomes-hubs/); [TCT Magazine](https://www.tctmagazine.com/additive-manufacturing-3d-printing-news/latest-additive-manufacturing-3d-printing-news/protolabs-rebrands-hubs-as-protolabs-network/)
- For Fictiv, Protolabs and Quickparts, searches returned only descriptions of web instant-quote workflows (Quickparts "QuickQuote", Fictiv's instant quoter that "often falls back to manual quoting") and no developer API — [OpenSpindle comparison](https://openspindle.com/compare/xometry-vs-protolabs-vs-fictiv); [NBC News archive: Quickparts e-commerce portal](https://www.nbcnews.com/news/amp/wbna42460415)

### Inferences
- For PartCAD's three calls, Craftcloud is the closest fit in this group: it has a published machine-readable spec, multi-vendor pricing, shipping options inside the cart response, an order endpoint and an order-status endpoint. Treatstock is second; its API is smaller, and its docs and client are years old.
- An OpenAPI spec that is served live, whose `appId` enum includes a current HP deployment, suggests the Craftcloud spec reflects the production API in 2026 rather than a stale document.
- Xometry should be dropped as a buyer-side target unless Xometry grants a private enterprise integration. Its public API faces the supplier side, and its CAD add-ins (below) use a private API.

### Gaps
- No public API documentation was found for Fictiv, Quickparts or Protolabs Network/Hubs. Absence in search is not proof that no private or partner API exists.
- The i.materialise and Sculpteo pages could not be fetched (404/403), so their current status, and whether they still accept API orders in 2026, is unverified.
- No historical documentation of the 3D Hubs public API, or of its retirement date, was found in this pass.

## What each API can do: upload formats, instant price, catalogue, shipping, cart, order, status, webhooks

### Takeaway
Craftcloud covers the whole chain (upload → multi-vendor price → cart with per-vendor shipping options → order → payment → per-vendor status), but no webhooks were found, and the material catalogue is a separate service that is not in the spec. Treatstock covers upload (STL/PLY/3MF), price by material/colour, a colour catalogue and order creation. Shapeways covers materials, upload, shipping options, orders and status. **None of the documented buyer-side APIs states that it accepts STEP**, so a PartCAD plugin should plan to send STL (or 3MF where supported).

### Cited Findings
**Craftcloud**
- The upload response gives `modelId`, `fileName`, `fileUnit`, `area`, `volume`, `dimensions`, `thumbnailUrl` and `sceneId`; parsing is asynchronous. All examples use `testmodel.stl` — [shapeMint notes](https://github.com/MattSharp05/shapeMint/blob/HEAD/docs/API_information/craftcloud_api_merged.md); [Kiln blog](https://www.kiln3d.com/blog/craftcloud-live)
- `createPriceRequest` takes `currency`, `countryCode`, `models[{modelId, quantity, scale}]`, `materialConfigIds`, `vendorIds`, `cartId` and `topMaterialConfigsOnly`. The currency enum is USD, EUR, GBP, CAD, AUD, CHF, NOK, JPY, ILS — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json); [shapeMint notes](https://github.com/MattSharp05/shapeMint/blob/HEAD/docs/API_information/craftcloud_api_merged.md)
- `cartResponse` requires `cartId`, `countryCode`, `currency`, `estDeliveryTime`, `expiresAt`, `models`, `minimumProductionPrice`, `quotes`, `shippings`, `items` and `amounts`. Each shipping entry has `shippingId`, `vendorId`, `name` (e.g. "UPS Ground"), `deliveryTime` (e.g. "3-5"), net `price`, `priceInclVat`, `currency`, `type` (`standard|express`) and `carrier` — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- `POST /v5/order` takes `cartId` and `user{emailAddress, shipping{firstName, lastName, address, city, zipCode, countryCode, phoneNumber}, billing{..., isCompany}}`, plus `customsInformation`. It returns `orderId`, `orderNumber` and `amounts.total{totalNetPrice, totalGrossPrice, currency}` — [shapeMint notes](https://github.com/MattSharp05/shapeMint/blob/HEAD/docs/API_information/craftcloud_api_merged.md)
- `orderStatusResponse` gives the status per vendor, `type ∈ {ordered, in_production, shipped, received, blocked, cancelled}` with dates, plus `estDeliveryTime` — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- The spec says a "Reverse lookup of the materialId has to be done via the material-catalog", but the spec itself has no material-catalog path. `api.craftcloud3d.com/material-catalog` is behind Cloudflare (403) — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json); probed directly
- I found no webhook in the spec (zero occurrences of "webhook"). Status is pulled with `GET /v5/order/{orderId}/status` — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- Network size: "150+ print shops", six technologies (FDM, SLA, SLS, MJF, metal/DMLS named) — [Kiln blog](https://www.kiln3d.com/blog/craftcloud-live). A review notes the homepage says "more than 150" partners while the directory says "more than 180" — [3dprintbounty review](https://3dprintbounty.com/blog/craftcloud-review)

**Treatstock**
- "Our API supports the following 3D printing file formats: STL, PLY and 3MF." Quote prices come per `materialGroup`/`printer`/`color`/`price`/`url`. The minimum price defaults to PLA, white; `not_calculated_yet` means retry. The order body is `printablePackId`, `providerId`, `comment`, `location`, `shippingAddress` and `modelTextureInfo`, and the response is `orderId`, `total` and `url`. No webhook is described — [Treatstock API Documentation](https://www.treatstock.com/help/article/83-api-documentation)
- Known limitation: a price request returns only one result for each materialGroup and colour combination (GitHub issue). To change location, use ChangePrintablePack rather than re-uploading — [Treatstock/apiv2 issue #9](https://github.com/Treatstock/apiv2/issues/9)

**Shapeways**
- `POST /models/v1` takes a base64 file, `fileName`, `uploadScale` (1.0 = m, 0.001 = mm, 0.0254 = in), and flags for model rights and terms acceptance. There is no dedicated pricing endpoint: model info carries per-material prices. Shipping options come from `GET /cart/shipping-options/v1`. `POST /orders/v1` takes items `{modelId, materialId, quantity}`, the address, `paymentMethod` and `shippingOption`. `GET /orders/{id}/v1` gives statuses placed, in_production, shipped and cancelled. The format list is only a link to an FAQ (STL in the examples) — [Shapeways API quick start](https://developers.shapeways.com/quick-start)

**JLCPCB 3D printing**
- Covers model upload, parsing results, pricing, and order creation and tracking. The formats are not stated on the public page — [JLCPCB API article](https://jlcpcb.com/help/article/jlcpcb-online-api-available-now)
- A third-party MCP server exposes `jlcpcb_tdp_create_order`, `..._order_list`, `..._order_detail` and `..._order_process` tools, and warns that create-order places a real, paid order (secondhand) — [glama.ai jlcpcb-mcp](https://glama.ai/mcp/servers/Eyalm321/jlcpcb-mcp/tools/jlcpcb_tdp_create_order)

### Inferences
- No API in this group was confirmed to accept STEP. PartCAD should export STL (or 3MF for Treatstock) for these plugins and keep STEP for CNC-oriented services. This is inferred from the docs not listing STEP; Craftcloud's web front end may accept more formats than its examples show.
- Craftcloud's `quotes` and `shippings` are per vendor. A PartCAD "cart" spanning parts that land at different vendors gets several shipping lines, and `quote` should sum `amounts` from `cartResponse` rather than compute a total itself.
- Mapping PartCAD's `caps` to Craftcloud needs the material catalogue, which is not in the published spec. That makes `caps` the weakest of the three calls for Craftcloud.

### Gaps
- Craftcloud's accepted upload formats (beyond STL) and its material-catalog endpoint are undocumented in what I could reach.
- Whether Craftcloud exposes any webhook or notification beyond the price WebSocket was not found.
- JLC3DP's file formats, payload shapes and status values are behind the approval gate.

## Access, auth, cost, sandbox, rate limits, per-user credentials, ToS and affiliate terms

### Takeaway
Craftcloud's quote and order endpoints work **without authentication**: no `securityDefinitions` apply to them, only a Net30 settlement call uses basic auth, and orders are guest orders keyed by email. That is easy to integrate but does not give "each user logs in with their own account". Shapeways has the cleanest per-user model (OAuth2 authorization_code, self-serve app registration, free). Treatstock uses a single partner `private-key` that "should not be disclosed to users", which is awkward for an open-source client where every user would need their own key. JLCPCB and PCBWay are approval-gated partner programmes.

### Cited Findings
- **Craftcloud:** the spec's `securityDefinitions` is empty except for `basicAuth`, which is applied only to `PATCH /v5/payment/net30/{paymentId}/settle`. The public endpoints carry no auth requirement — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- Craftcloud: "public endpoints work without an API key … no onboarding required. If you want orders tied to a Craftcloud account, you can set an API key, but it's optional" (developer blog, secondhand) — [Kiln blog (search snippet)](https://www.kiln3d.com/blog/craftcloud-live)
- Craftcloud is "completely free to use and you don't have to create an account to get quotes or place an order" — [All3DP: Craftcloud simply explained](https://all3dp.com/1/craftcloud-by-all3dp-simply-explained/)
- Craftcloud has a referral-voucher endpoint (`POST/GET /v5/referral`, "Generate user referral voucher"). The partner page is a generic form for print shops wanting to join, and no integrator affiliate or revenue-share programme was found — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json); [Craftcloud Become a partner](https://craftcloud3d.com/en/become-a-partner)
- Craftcloud has no sandbox environment, but payment requests carry `isTestOrder: boolean` (default false) — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- **Treatstock:** authentication is a `private-key` query parameter (full access), with a separate `public-upload-key` for uploads only. The key "should not be disclosed to users". Rate limits are concurrent connections per key: GET 7, POST 15, PUT 30. No sandbox is mentioned. The upload response includes `affiliate_price` and `affiliate_currency` — [Treatstock API Documentation](https://www.treatstock.com/help/article/83-api-documentation)
- Treatstock's API-partner page: "Every successful order through the API will generate an additional source of income for your website!" No rates are given; contact sales — [Become an API partner](https://www.treatstock.com/help/article/113-become-an-api-partner)
- **Shapeways:** OAuth2 at `https://api.shapeways.com/oauth2/token`. `client_credentials` serves the app owner only (one-hour token, no refresh token); `authorization_code` via `/oauth2/authorize` with refresh tokens serves apps used by other Shapeways users. Apps are registered at `/manage-apps` with a verified account, with no approval step stated. "API access is free". Rate limits are not stated. Some examples point at an internal dev host — [Shapeways API quick start](https://developers.shapeways.com/quick-start); [developers.shapeways.com](https://developers.shapeways.com/)
- Older Shapeways clients use OAuth 1.0a, and no deprecation notice for either OAuth version was found — [reshape gem docs](https://www.rubydoc.info/gems/reshape/0.2); [shapecode-php](https://github.com/jublo/shapecode-php)
- **Xometry:** access by email request, as a partner; keys come from the Workcenter "Developer Token" page; rate limits are per partner — [Xometry developer docs](https://developer.xometry.com/docs/getting-started)
- **JLCPCB:** apply at api.jlcpcb.com with a JLCPCB account. Approval weighs "the partner's previous orders at JLCPCB" and the company/business situation. Support does no code reviews. Partners may not use the JLCPCB trademark or logo or put "JLC" in URLs, on pain of suspension. Auth, fees and sandbox are not stated publicly — [JLCPCB API access article](https://jlcpcb.com/help/article/jlcpcb-online-api-available-now)
- **PCBWay:** apply by email (anson@pcbway.com), reviewed by the PCBWay team, partners only — [PCBWay API Cooperation](https://www.pcbway.com/api_cooperation.html)
- **Sculpteo** (secondhand): "access to the API is free for our partners", by contact — [Sculpteo API services (snippet)](https://www.sculpteo.com/en/services/api-services/)

### Inferences
- **Shapeways** is the one candidate whose auth model matches PartCAD's "each user logs in with their own credentials" directly (OAuth2 authorization code). An open-source plugin would still need a client_id/secret, either one registered by PartCAD and shipped (public clients are a known weakness of OAuth2 without PKCE, and none is documented here) or one registered by each user at `/manage-apps`.
- **Craftcloud**'s user identity is just the email and addresses sent with the order. A plugin can work with no credentials at all. The "own credentials" requirement would be met only by the optional API key (secondhand, undocumented).
- **Treatstock**'s one-key-per-partner model means each PartCAD user would have to obtain their own partner `private-key`, or PartCAD would have to hold one centrally. Holding one centrally conflicts with "should not be disclosed to users" in a client-side open-source plugin.
- JLCPCB's gate (order history, business review) and PCBWay's email application make them unsuitable for a self-serve, per-user plugin.

### Gaps
- No terms-of-service text explicitly allowing or forbidding use of these APIs in third-party open-source tools was found for any service.
- Craftcloud's rate limits, how its optional API key is issued, and any affiliate share for integrators are undocumented in sources I could reach.
- Treatstock affiliate percentages are not published.

## Payment flow: stored account or invoice, or a redirect to checkout?

### Takeaway
Craftcloud creates the order first and then a payment session: a hosted **Stripe Checkout URL**, a PayPal order, an Adyen session, or an invoice payment executed with a secret token, including Net30. So `order` would return a URL for the user to pay at. Shapeways charges the credit card stored in the user's account. Treatstock's API returns an order URL in its "workbench", and the payment mechanics are not described.

### Cited Findings
- Craftcloud `POST /v5/payment/stripe`: "Creates a Stripe Checkout session and redirects to the Stripe Checkout page". The request takes `orderId`, `returnUrl`, `cancelUrl` and `isTestOrder`; the response is `{id, url}` (the "URL of the hosted Stripe checkout page") — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- Craftcloud invoice path: `POST /v5/payment/invoice` (`orderId`, `isTestOrder`), then `PATCH /v5/payment/invoice/{paymentId}` with a "Secret token" and an optional `net30: true` ("Execute order under Net 30 payment terms"). `POST /v5/payment/quote` means "Create quote for order and attach invoice payment" — [Craftcloud API spec](https://api.craftcloud3d.com/api-docs.json)
- Shapeways: orders are charged to the credit card saved in the user's account settings (`paymentMethod: credit_card`). One example includes an unexplained `paymentVerificationId` — [Shapeways API quick start](https://developers.shapeways.com/quick-start)
- Treatstock: the order response is `orderId`, `total` and a `url` to the order in the workbench, and no payment endpoint is described. The upload also returns `redir` and `widgetUrl`/`widgetHtml` for an embedded ordering widget; the model is "only valid for 24 hours" — [Treatstock API Documentation](https://www.treatstock.com/help/article/83-api-documentation)
- An older Craftcloud integration (the cults/all3dp Ruby gem) only creates a configuration and "redirect[s] your users to the given URL" (`app.craftcloud3d.com/configuration/...`); its v2.0.0 switched to `customer-api.craftcloud3d.com` — [cults/all3dp README](https://github.com/cults/all3dp); [CHANGELOG](https://github.com/cults/all3dp/blob/HEAD/CHANGELOG.md)

### Inferences
- For Craftcloud, PartCAD's `order` would naturally return the `orderId` plus a payment URL (Stripe) to open in the user's browser, or use the invoice/quote path for business users. Full headless purchase through the API is not possible without the user completing a hosted payment step, unless the invoice token flow (likely emailed to the user) is used.
- A simpler, still-supported fallback for Craftcloud is the "configuration" link (`POST /v5/configuration` → `app.craftcloud3d.com/configuration/<id>`). PartCAD would hand the user a pre-filled cart and leave checkout to the website.

### Gaps
- Where the Craftcloud invoice "secret token" comes from (an email to the buyer?) is not stated in the spec.
- How Treatstock orders created by the API are paid (partner balance, invoice or redirect) is not documented publicly.
- How JLC3DP API orders are paid (account balance or stored card) is not public.

## Evidence of working third-party integrations and open-source clients

### Takeaway
Craftcloud has the most active third-party use in 2025–2026: Kiln's agent integration (Feb 2026), several GitHub projects calling `api.craftcloud3d.com`, HP's MJF portal on the same API, and the long-standing cults/all3dp gem. Treatstock has an official PHP client and a Thingiverse print-service integration. Xometry's CAD integrations (Fusion, SOLIDWORKS, Inventor add-ins) exist but use no public API.

### Cited Findings
- Kiln's Craftcloud v5 adapter (Feb 2026) does model upload, price polling (HTTP or WebSocket), cart creation, order placement with "full address handling", order status tracking and cancellation, covered by 81 tests. Users either go through a hosted path or use "direct mode with their own Craftcloud credentials" — [Kiln blog](https://www.kiln3d.com/blog/craftcloud-live)
- A GitHub code search for "api.craftcloud3d.com" returns adapters in several public repos, e.g. `nirholas/three.ws` (`api/_lib/print/adapters/craftcloud.js`), `JadeKim042386/3D-Print` (`server/src/providers/craftcloud.ts`), `ankitrawat448/FabFoundry` (`src/lib/craftcloud.ts`) and `wearebeautiful/wearebeautiful-web`. The code search was run via the GitHub CLI; the contents of these repos were not reviewed — [cults/all3dp](https://github.com/cults/all3dp) (the one repo whose code was read)
- Cults (a French 3D model marketplace) maintains the `all3dp` Ruby gem that sends model URLs to Craftcloud and redirects users — [cults/all3dp](https://github.com/cults/all3dp)
- Craftcloud technology powers HP's on-demand MJF parts service — [VoxelMatters](https://www.voxelmatters.com/hp-and-craftcloud-launch-on-demand-mjf-parts-portal-with-instant-quoting/); [All3DP](https://all3dp.com/4/craftcloud-and-hp-launch-new-on-demand-3d-printing-service-to-accelerate-mjf-part-sourcing/)
- Treatstock: an official PHP client — [Treatstock/apiv2](https://github.com/Treatstock/apiv2); a Thingiverse 3D printing service article in its help centre — [Treatstock help: Thingiverse 3D Printing Service](https://www.treatstock.com/help/article/91-thingiverse-3d-printing-service); and an embeddable widget — [3DPrinting.com on Treatstock's widget](https://3dprinting.com/news/treatstocks-widget-makes-adding-a-3d-printing-service-to-your-website-easier-than-ever)
- Xometry: the free "Instant Quote Add-In for Autodesk Fusion", co-developed with Autodesk; Xometry EU users can use the same app since a 2024 update — [Autodesk App Store](https://apps.autodesk.com/FUSION/en/Detail/Index?id=5430166430880711212&ln=en&os=Win32_64). The SOLIDWORKS and Inventor add-ins are reported by a third-party blog (unverified) — [topbubbleindex](https://www.topbubbleindex.com/blog/xometry-design-resources/); procurement punchout (Coupa, Ariba, SAP) per a directory (unverified) — [softwarefinder](https://softwarefinder.com/manufacturing-software/xometry)
- Shapeways: legacy community clients (OAuth 1.0a era) — [reshape gem](https://www.rubydoc.info/gems/reshape/0.2); [shapecode-php](https://github.com/jublo/shapecode-php). An unofficial OpenAPI transcription exists — [apis.io Shapeways Models API](https://apis.io/apis/shapeways/shapeways-models-api/)
- JLCPCB: a community MCP server for its API (secondhand) — [glama.ai jlcpcb-mcp](https://glama.ai/mcp/servers/Eyalm321/jlcpcb-mcp/tools/jlcpcb_tdp_order_list)

### Inferences
- The number of 2025–2026 hobby and agent projects calling Craftcloud without any partner agreement is good practical evidence that an unauthenticated third-party integration works and is tolerated. It is not evidence of formal permission.
- No Python client library for Craftcloud or Treatstock was found. A PartCAD plugin would be the first in Python, but the Swagger spec makes generating one straightforward.

### Gaps
- No Onshape, Blender, Printables or slicer (Cura, PrusaSlicer, Bambu Studio) integration was confirmed for any of these services in this pass.
- The Craftcloud adapters found on GitHub were not reviewed for how well they work or whether they are maintained.

## Company health and status (acquisitions, bankruptcies, API deprecations)

### Takeaway
Craftcloud and its API are live and maintained in 2026. Shapeways went through Chapter 7 in July 2024, was relaunched by its founders from Eindhoven in December 2024, and is active in 2026 (Thangs print-on-demand, defence and robotics partnerships, a move to a new site). Its developer API still responds, but its documentation and endpoints date from 2012–2013 and nothing says it is supported. Hubs is now Protolabs Network, with no public API.

### Cited Findings
- Shapeways filed Chapter 7 in July 2024. The founders and the Eindhoven team bought the assets and relaunched the brand on 3 December 2024, with Marleen Vogelaar returning as CEO; Thangs print-on-demand launched in early 2025 and FDM was added in 2025 — [Fabbaloo](https://www.fabbaloo.com/news/print-on-demand-beta-on-thangs-marks-key-milestone-in-shapeways-relaunch-strategy); [3DPrint.com: relaunched with all assets](https://3dprint.com/314952/shapeways-relaunched-with-all-assets-under-one-roof/); [Tom's Hardware: Shapeways acquires Thangs](https://www.tomshardware.com/3d-printing/newly-resurrected-shapeways-acquires-thangs-in-surprising-announcement)
- 2026: Shapeways joined the Dutch defence industry association NIDV on 16 April 2026 and partnered with FuturePulse 2026 in June 2026. A relocation to Strijp T, Eindhoven, is planned for late 2026 — [Shapeways Press Corner: NIDV](https://www.shapeways.com/presscorner/shapeways-joins-nidv); [Shapeways Press Corner: FuturePulse](https://www.shapeways.com/presscorner/shapeways-partners-with-future-pulse-2026); [Fabbaloo: new high-capacity site](https://www.fabbaloo.com/news/revived-shapeways-prepares-for-future-growth-with-new-high-capacity-site)
- Shapeways API history: the SOAP API was deprecated (forum thread "Deprecating the SOAP API: April 30th", 2014); the REST API and developer portal launched earlier (TechCrunch) — [Shapeways forum](https://shapeways.com/forum/t/deprecating-the-soap-api-april-30th.17897); [TechCrunch](https://techcrunch.com/?p=772570). The live API discovery document still reports revision "20121123" — [api.shapeways.com](https://api.shapeways.com/)
- Hubs: Protolabs acquired 3D Hubs (January 2021), renamed it Hubs, then Protolabs Network (January 2024); existing accounts carried over — [3dprintingjournal](https://www.3dprintingjournal.com/p/01-19-2021-protolabs-acquired-the); [Fabbaloo: From 3D Hubs to Protolabs Network](https://www.fabbaloo.com/news/from-3d-hubs-to-protolabs-network-evolution-of-a-3d-printing-service)
- Craftcloud: the v5 API health check answered `{"status":"ok"}` on 2026-11-22 (probed directly), and the spec includes 2025-dated examples and a Net30 settlement endpoint — [health check](https://api.craftcloud3d.com/v5/health_check); [spec](https://api.craftcloud3d.com/api-docs.json)
- Treatstock: the website is live (footer "© 2026"), but the API docs' examples date from 2019–2020 and the official client was last updated in 2022 — [Treatstock API Documentation](https://www.treatstock.com/help/article/83-api-documentation); [Treatstock/apiv2](https://github.com/Treatstock/apiv2)
- Xometry: still publicly traded, with AI quoting-engine updates in 2025, e.g. injection-moulding instant estimates in October 2025 — [Xometry release notes](https://www.xometry.com/release-notes/)
- JLCPCB: API page updated 10 Nov 2026 — [JLCPCB API article](https://jlcpcb.com/help/article/jlcpcb-online-api-available-now)

### Inferences
- Shapeways' API answering in 2026 does not mean it is supported for new orders. A plugin built on it should be treated as experimental until Shapeways confirms. Mailing api@shapeways.com, as the old docs suggest, is the obvious next step.
- Treatstock's API appears to be in maintenance mode: unchanged docs and a client untouched since 2022.

### Gaps
- No public statement was found on whether the Shapeways REST API (orders in particular) is officially supported after the 2024 relaunch.
- Sculpteo's ownership and status after BASF Forward AM's 2024 insolvency was not verified in this pass. Its API page's status is unknown (fetch blocked).
- No date for the retirement of the historical 3D Hubs API was found.
