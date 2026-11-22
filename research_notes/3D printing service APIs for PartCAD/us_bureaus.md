# US 3D printing service bureaus and print farms: developer APIs for a PartCAD `manufacturer` plugin (as of Nov 2026)

Scope: direct manufacturers and print farms with a US presence (Craftcloud excluded as covered elsewhere). PartCAD's plugin needs three calls (`caps`, `quote` returning total + ISO 4217 currency + cart id, `order` by cart id), the user's own credentials, and an upload of STEP (STL can be exported).

Sources: where a fact comes from the vendor's own docs or machine-readable spec it is marked **(primary)**. Several "no API" findings come from Supergood's "API report cards", a vendor that sells unofficial API layers over web apps. That is a commercial interest, so those findings are marked **(secondhand, unverified)**.

## 1. Which services have a public, documented API (docs URL, style, OpenAPI)?

### Takeaway
Only a handful of US-reachable services publish an API that a buyer-side, open-source tool can use. These are **Slant 3D** (OpenAPI 3.0.3, REST, Boise ID), **3DAPI / dapi.digital** (OpenAPI 3.1, REST, US + EU production network), and **Shapeways** (REST v1 with OAuth2, though the relaunched company is Dutch). **Sculpteo** still hosts a partner web API, but it is French-owned now. Xometry's public developer API is supplier-side only. Protolabs, Fictiv, Stratasys Direct, Quickparts, SyBridge, Prototek, RapidMade, eMachineShop, SendCutSend, OSH Cut and Ponoko have no public buyer API today. Formlabs, Markforged, Prusa and Bambu offer printer and fleet APIs, not parts-ordering services.

### Cited Findings

**Slant 3D (Boise, Idaho), API v2**
- The spec is published as OpenAPI 3.0.3, "Slant 3D V2 API", version 2.0.0, at `https://slant3dapi.com/v2/api/openapi.json`. Its server is `https://slant3dapi.com/v2/api`. The description reads: "3D Printing and manufacturing API that exists on top of the Slant 3D print farm... This spec is for automated tools and AI Agents." **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- The human docs are at `https://slant3dapi.com/documentation/introduction`. The marketing page is "Slant 3D Printing API — Manufacturing as an Endpoint" and has a "Get an API key" link to slant3dapi.com. **(primary)** — [Slant 3D API page](https://www.slant3d.com/slant-3d-printing-api)
- The endpoints, read from the spec, are: **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
  - Files: `POST /files/direct-upload`, `POST /files/confirm-upload`, `GET/PATCH/DELETE /files/{publicFileId}`, `POST /files/batch`, and `POST /files/{publicFileId}/estimate`.
  - Catalogue: `GET /filaments`, `GET /components` (with `search` and `categories`), and `GET /stationery`.
  - Orders: `POST /orders` drafts an order, `POST /orders/{publicOrderId}` processes it ("begin production and charge payment"), `DELETE /orders/{publicOrderId}` cancels it, and `GET /orders`, `/orders/search` and `/orders/batch` read orders.
  - Platforms and webhooks: `/platforms`, `/platforms/{id}/webhook-secret`, test, dead-letter and resend endpoints, and `POST /slant/webhook`.
  - Other: `GET /platforms/stripe/public-key`, `GET/POST /apiKey`, `GET /usage`, `GET /health/status`, and `POST /files/openScad` ("Convert OpenSCAD code to STL", limited to 100 generations an hour).
- The spec carries `x-agent-hints`: "rate-limit: 100 requests per minute", "max-api-keys: 3", "5 enabled platforms per account", and "order-workflow: Upload files → Draft order → Process Order → Fulfillment Label Created Internally → Webhook Order Updates". **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- Slant also runs a public MCP server at `https://www.slant3d.com/mcp` (Streamable HTTP). It needs no API key or sign-in. Its tools are `quote_upload_part`, `quote_set_quantity`, `quote_shipping_options`, `quote_checkout` (which creates a payment link) and `list_materials`. It takes STL files by URL or base64. **(primary)** — [Slant 3D MCP server](https://www.slant3d.com/mcp-server)

**3DAPI (dapi.digital), API v2**
- The docs are at `https://public-api.dapi.digital/docs`, with base URL `https://public-api.dapi.digital` and `/v2` paths. They publish OpenAPI 3.1 for designers and integrators, OpenAPI 3.0 for print farms, an Arazzo 1.0 workflow document and `llms.txt`. An MCP server is available as `npx -y @dapi-digital/mcp`. **(primary)** — [3DAPI llms.txt](https://public-api.dapi.digital/docs/llms.txt)
- Money is represented as `{ "amount": 5000, "currency": "usd" }`, an integer in minor units with an ISO currency code. Writes accept an `Idempotency-Key`. **(primary)** — [3DAPI llms.txt](https://public-api.dapi.digital/docs/llms.txt)
- 3DAPI is a network, not a single factory. It is "based in the US and Europe". Orders are "made at a production centre near the buyer" and are assigned to "a production partner". **(primary)** — [3DAPI vs Shapeways page](https://www.dapi.digital/compare/3dapi-vs-shapeways); [3DAPI business guide](https://public-api.dapi.digital/docs/guides/integrator-business.md)

**Shapeways (relaunched December 2024, Eindhoven)**
- The developer portal at `developers.shapeways.com` is still live. It documents `GET /materials/v1`, `POST /models/v1`, `GET /models/{modelId}/v1`, `POST /orders/v1`, `GET /orders/{orderId}/v1` and `GET /cart/shipping-options/v1`. **(primary)** — [Shapeways API docs](https://developers.shapeways.com/docs)
- The portal says "API access is free" and invites contact about volume discounts. It shows no version date and no notice about the relaunch. **(primary)** — [Shapeways developer portal](https://developers.shapeways.com/)
- Shapeways Holdings filed for Chapter 7 in July 2024. A new team bought the name, the website and the Eindhoven factory from the Dutch and US trustees and relaunched the brand on 3 December 2024, focused on B2B. The designer marketplace was not restored. **(secondhand, via search summary)** — [cadmore.com](https://cadmore.com/blog/what-happened-to-shapeways); [yespress.io](https://yespress.io/shapeways)

**Sculpteo**
- The web API docs are still hosted at `sculpteo.com/en/developer/webapi/`. They cover direct upload, web2web upload, getting a price by design UUID, and placing an order. The pages show a placeholder date of "1970-01-01", so how current they are is unclear. **(primary, but undated)** — [Sculpteo API docs](https://www.sculpteo.com/en/developer/webapi/); [price endpoint](https://www.sculpteo.com/developer/webapi/order/price/); [order endpoint](https://www.sculpteo.com/developer/webapi/order/order/)
- 3D Prod, a French company, has acquired Sculpteo from BASF. The deal date is not stated in the snippets. **(trade press)** — [TCT Magazine](https://www.tctmagazine.com/explained-why-3d-prod-sculpteo-have-merged/); [3D Printing Journal](https://www.3dprintingjournal.com/p/3d-prod-acquires-sculpteo-and-aims)

**Xometry**
- `developer.xometry.com` exists, but it is a **manufacturing-partner (supplier) API**. It covers jobs, job media, line-item status, offers to accept or reject on the job board, and webhooks. It has no endpoints for quote creation, file upload, pricing or order placement. **(primary)** — [Xometry llms.txt](https://developer.xometry.com/llms.txt)
- Access is requested by email: "Please email support@xometry.com to request API access", giving your Partner Name. Job-board offers need further approval. **(primary)** — [Xometry Getting Started](https://developer.xometry.com/docs/getting-started)
- Buyer-side integrations are closed or partner-only:
  - an Instant Pricing App for Onshape **(primary)** — [Xometry Onshape app](https://www.xometry.com/resources/blog/introducing-the-xometry-onshape-app)
  - cXML/PunchOut and ERP integration for enterprises **(primary)** — [Xometry PunchOut](https://www.xometry.com:443/xometry-enterprise/xometry-integration-punchout)
  - the Instant Quoting Engine embedded in Thomasnet.com **(trade press)** — [DE247](https://www.digitalengineering247.com/article/xometry-launches-digital-sourcing-tools-on-thomasnet.com/additive-manufacturing)

**No public buyer API found**
- **Protolabs (US)**: The 2026 ProDesk launch describes a browser-based AI quoting and DFM platform and does not mention an API. Fusion 360 integration was built by Autodesk. **(primary press release / trade)** — [Protolabs ProDesk press release](https://protolabs.gcs-web.com/news-releases/news-release-details/protolabs-introduces-prodesk-ai-enabled-manufacturing-platform); [Autodesk Fusion blog](https://www.autodesk.com/products/fusion-360/blog/proto-labs-online-quoting-services-are-now-available/)
  - Supergood grades Protolabs F. **(secondhand)** — [Supergood (via SendCutSend page)](https://supergood.ai/api-report-card/sendcutsend)
- **Protolabs Network (Hubs)**: Help pages describe web upload and checkout only. Non-standard requests go to `networksales@protolabs.com`. **(primary help pages)** — [Hubs help center](https://www.hubs.com/help-center/how-to-get-a-quote/)
- **Fictiv**: Supergood reports that the developer and docs subdomains do not resolve, that `api.fictiv.com` returns 403, and that the only integration is cXML PunchOut arranged through sales. **(secondhand, unverified)** — [Supergood: Fictiv](https://supergood.ai/api-report-card/fictiv)
  - Fictiv's own help pages describe web quoting only. **(primary)** — [Fictiv help](https://www.fictiv.com/help/fictiv-teams/managing-quotes-and-orders-in-a-team)
- **SendCutSend**: Supergood (verified Nov 2026) says there is "no public API and no developer portal". `api.sendcutsend.com` returns route-not-found. Quoting and ordering happen only at app.sendcutsend.com. The only developer-facing item is an Autodesk Fusion plugin. **(secondhand, unverified)** — [Supergood: SendCutSend](https://supergood.ai/api-report-card/sendcutsend)
- **OSH Cut**: The site describes web upload, instant nested pricing and checkout, plus net-30 terms for active customers. I found no API documentation. **(primary, absence)** — [OSH Cut online DFM ordering](https://oshcut.com/services/online-dfm-ordering); [OSH Cut FAQ](https://oshcut.com/faq)
- **Ponoko**: The Personal Factory API and App Gateway (2011–2012, Autodesk 123D as the first app) are **historical**. Supergood reports no developer portal today and an API host that returns an error. **(historical: trade press; current: secondhand)** — [Core77](https://core77.com/posts/19438/ponokos-personal-factory-5-and-app-gateway-autodesk-123d-19438); [Supergood: Ponoko](https://supergood.ai/api-report-card/ponoko)
  - The old Ruby client `Ponoko/ponoko` was last updated in 2023. — [GitHub search via gh](https://github.com/Ponoko/ponoko)
- **Stratasys Direct**: Quoting is through "RapidQuotes", a web platform, and complex jobs go to the team. No API is mentioned. **(primary)** — [Stratasys Direct RapidQuotes](https://www.stratasys.com/en/stratasysdirect/resources/articles/rapidquotes-online-quoting/)
- **Quickparts**: The former 3D Systems on-demand business was sold to Trilantic for $82M in 2021 and became independent Quickparts. It offers web QuickQuote and no API was found. — [3DPrint.com](https://3dprint.com/285210/3d-systems-finalizes-sale-of-on-demand-business-will-operate-as-quickparts/); [DE247](https://www.digitalengineering247.com/article/3d-systems-quickparts-enhances-instant-quote-functionality/rapid-prototyping)
- **RapidMade, Prototek, SyBridge, eMachineShop**: Each has web instant quoting only, and no API was found. eMachineShop requires its own design software to quote.
  - [RapidMade instant quote](https://rapidmade.com/instant-quote-info/)
  - [Prototek instant quoting](https://prototek.com/press-release/prototek-announces-the-launch-of-instant-quoting-for-additive-manufacturing/)
  - [SyBridge On-Demand](https://www.fastradius.com/cloud-manufacturing)
  - [RapidDirect review (eMachineShop claim, secondhand)](https://www.rapiddirect.com/blog/8-best-digital-manufacturing-platforms-with-instant-quotes-2026-review/)
- **Forerunner 3D**: No search results at all.

**Printer and fleet APIs, not ordering services**
- **Formlabs**: The developer portal (`developer.formlabs.com`) offers the Local API / PreForm API for preparing, slicing and sending print jobs, the Dashboard Web API for printer groups, queues and print history, and a Python SDK. It has no on-demand parts-ordering API. **(primary)** — [Formlabs developer portal](https://developer.formlabs.com/)
  - The Web API base is `api.formlabs.com/developer/v1` with an OAuth client-credentials token. **(secondhand catalogue)** — [apis.io Formlabs Printers API](https://apis.io/apis/formlabs/formlabs-printers-api/)
- **Markforged Eiger**: API v3 at `eiger.io/developer/spec` uses HTTP Basic auth with an access key and secret. Only the organisation admin can create keys. It covers devices, builds, print jobs and parts, and is included for Eiger Fleet customers. **(primary spec page, via search summary)** — [Eiger API spec](https://www.eiger.io/developer/spec)
- **Prusa Connect**: Public APIs are limited to a Camera API and the local PrusaLink API spec. No print-farm or fleet cloud API is documented. **(primary help pages + forum)** — [Prusa Connect Camera API](https://help.prusa3d.com/es/article/prusa-connect-camera-api_569012); [Prusa forum](https://forum.prusa3d.com/forum/general-discussion-user-experience-ideas/prusa-connect-api-for-automation)
- **Bambu Lab**: Farm Manager is local and cloud-free. Partners get the Bambu Local Server SDK by application. Cloud APIs are only community reverse-engineered, and the 2025 Authorization Control System restricts third-party writes. — [Bambu blog: Farm Manager](https://blog.bambulab.com/bambu-lab-introduces-local-fleet-control-with-bambu-farm-manager/); [Bambu blog: third-party integration](https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect); [community Cloud API](https://github.com/coelacant1/Bambu-Lab-Cloud-API)

**Other US print-on-demand services found**
- **Slant 3D "Teleport"** is Slant's store-connection product (Etsy, Shopify, Amazon, WooCommerce, Squarespace, TikTok Shop). It is built on the same API. — [Slant 3D API page](https://www.slant3d.com/slant-3d-printing-api)
- **3D Vikings, Printie and Shop3D** are store-connector print-on-demand services. Shop3D "also offers an API", per a comparison blog, but I found no documentation for it. Its Shopify app takes .stl and .obj. **(secondhand, unverified)** — [PrintPort3D comparison](https://www.printport3d.com/blog/best-3d-print-fulfillment-companies); [Shop3D Shopify app](https://apps.shopify.com/shop-3d)

### Inferences
- For a PartCAD `manufacturer` plugin today, **Slant 3D** and **3DAPI** are the only realistic US-anchored targets with self-describing OpenAPI specs that cover upload, quote, order, status and webhooks. **Shapeways** is a third, with an older and smaller surface, but it is EU-based now.
- Every big US bureau (Xometry, Protolabs, Fictiv, Stratasys Direct, Quickparts) gates buyer integration behind enterprise PunchOut, ERP or CAD-vendor partnerships. None of them is reachable by an open-source plugin using an ordinary end user's credentials.

### Gaps
- I could not read the Slant 3D human docs (the page is JavaScript-rendered), so I have no exact text on self-serve key issuance, v1 deprecation, or terms.
- I did not fetch the Shapeways auth page. A third-party transcription says OAuth2 with client credentials for single-account apps and authorization code plus refresh for multi-user apps.
- I did not confirm the date of the Sculpteo sale or whether Sculpteo still has a US office or presence.
- I found no information at all on Forerunner 3D.

## 2. Capabilities: upload formats, pricing, catalogue, shipping, cart, order, status, webhooks

### Takeaway
**Slant 3D's API accepts STL only**, and its catalogue is FDM filaments (PLA, PETG, OPM). It returns an order draft with separate USD print and delivery costs, and has webhooks. **3DAPI accepts STEP/STP, STL, 3MF and OBJ**, has quotes, materials, shipping estimates, orders and webhooks, and uses explicit ISO currency. **Shapeways** has upload, materials with USD prices, shipping options and order placement. Sculpteo has upload, price and order.

### Cited Findings

**Slant 3D**

*Files and catalogue*
- The File schema `type` enum is `["stl"]`, described as "File type - currently only STL supported". **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- Uploading is a presigned S3 PUT from `POST /files/direct-upload`, followed by a mandatory `POST /files/confirm-upload`. Processing returns metrics: volume, weight, print-time estimate, bounding box, `supportRequired` and body count. **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- `GET /filaments` returns `publicId`, `name`, `provider`, `profile` (enum `OPM`, `PLA`, `PETG`), `color`, `hexValue` and `available`. It can be filtered with `?profile=PLA,PETG&color=red`. **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
  - The public MCP server lists "PLA, PETG, CF PETG, and OPM". — [Slant 3D MCP server](https://www.slant3d.com/mcp-server)
- STEP is accepted only by the separate Batch Production web flow, and Slant offers a separate STEP-to-STL converter tool. — [Slant 3D API page](https://www.slant3d.com/slant-3d-printing-api)

*Pricing and shipping*
- `POST /files/{publicFileId}/estimate` returns `subtotal`, `total`, `pricePerUnit`, `quantity`, `bodyChargeCost` and `oversizeSurcharge`. Every figure is "in USD" and covers the print only. It defaults to PLA Black when no filament is given. **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- `POST /orders` (the draft) takes `platformId`, `customer.details.email` and `customer.details.address`. The address fields are `name`, `line1`, `line2`, `city`, `state`, `zip` and `country`, with `country` defaulting to "US".
  - `items[]` holds entries of type `PRINT` (`publicFileServiceId`, `filamentId`, `quantity`), `COMPONENT` or `STATIONERY`.
  - The resulting Order has `publicId` ("SLANT_XXXXXXXXXX"), `deliveryCost` ("Shipping cost in USD"), `printingCost`, and `status` (`DRAFT`, `SUBMITTED`, `PRINTING`, `SHIPPED`, `CANCELLED`). **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- The MCP server gives quantity pricing with a "setup fee" and lead time, plus `quote_shipping_options` for carrier services and prices. — [Slant 3D MCP server](https://www.slant3d.com/mcp-server)

*Status and webhooks*
- Webhooks are configured per platform and signed with a per-platform secret. Event names in the spec include `payment.completed` and `payment.failed`, alongside order events such as `order.shipped`. Undelivered webhooks are kept for 30 days and can be resent. **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- Slant's analysis is a slicing estimate (size, volume, weight, time), not printable G-code. **(third-party PR)** — [MetaForge PR #1235](https://github.com/FidelOdok/MetaForge/pull/1235)

**3DAPI**

*Files and quotes*
- It quotes ".stl, .3mf, .obj, .step or .stp files of up to 250 MiB" and recommends 3MF. Parts are printed on Bambu Lab P1S printers with a 0.4 mm nozzle and 0.20 mm layers, with at most 4 colours per file. Walls must be at least 0.45 mm and the model needs a flat bottom. **(primary)** — [3DAPI file requirements](https://public-api.dapi.digital/docs/guides/file-requirements.md)
- Quoting is free. Before account approval there are 25 files per round and a daily quote cap; after approval quotes are unlimited. A quote's `price` is for one unit, and larger quantities cost less per unit. **(primary)** — [3DAPI business guide](https://public-api.dapi.digital/docs/guides/integrator-business.md)

*Shipping*
- Shipping is priced by destination zone and weight tier: small up to 600 g, medium up to 2 kg, large above, using volumetric weight (L×W×H/5000). `estimate_integrator_order_shipping` gives the exact figure and `get_shipping_rates` gives the rate card. **(primary)** — [3DAPI business guide](https://public-api.dapi.digital/docs/guides/integrator-business.md)

*Order lifecycle and webhooks*
- Orders move through `paid` → `assigned` → `in_production` → `shipped` → `completed`, with webhooks `order.paid`, `order.assigned`, `order.in_production`, `order.shipped` and `order.completed`.
- Shipped orders carry `shipping.carrier` and `tracking_number`.
- Production ships in 3–5 business days. Delivery takes 1–3 days from a local centre and 5–10 days internationally.
- **(primary)** — [3DAPI business guide](https://public-api.dapi.digital/docs/guides/integrator-business.md)

**Shapeways**
- Models upload through `POST /models/v1`. A `scale` field is "required for .stl / .obj / .vox, otherwise optional". The full format list was not shown on the page.
- Materials carry a `price` in USD.
- Shipping options give a price "without tax in USD" and minimum and maximum transit days.
- Orders are placed with `POST /orders/v1`. Uploads require `acceptTermsAndConditions` and `hasRightsToModel`.
- **(primary)** — [Shapeways API docs](https://developers.shapeways.com/docs)

**Sculpteo**
- The price endpoint takes a design UUID plus optional quantity and material. It returns unit and total cost, discount and expected delivery date. The order endpoint POST returns an order reference. Errors come back as bare HTTP status codes. **(primary, undated)** — [Sculpteo price](https://www.sculpteo.com/developer/webapi/order/price/); [Sculpteo order](https://www.sculpteo.com/developer/webapi/order/order/)

### Inferences
- **For Slant 3D**, a PartCAD plugin would have to export STL, not STEP.
  - `caps` maps onto `GET /filaments`, giving materials and colours. There are no finishes.
  - `quote` maps onto upload, confirm, then `POST /orders` as a DRAFT. The draft's `publicId` serves as the cart id, and the total is `printingCost` plus `deliveryCost`, with currency fixed to USD (the spec states it in descriptions, not as a field).
  - `order` maps onto `POST /orders/{publicOrderId}`.
  - Uploads are asynchronous (presigned PUT then confirm), so the plugin needs to wait for processing.
- **For 3DAPI**, STEP is accepted directly. Currency is returned explicitly in an ISO-like lower-case code (`usd`), which the plugin would upper-case to get ISO 4217.

### Gaps
- I do not know whether Slant's draft order computes `deliveryCost` for non-US addresses through the API. The marketing page mentions "international shipping", but the Batch page says parts ship domestically.
- I have not confirmed the exact 3DAPI quote and order endpoint paths. The operation names come from the docs (`estimate_integrator_order_shipping`, `cancel_integrator_order`, `list_integrator_orders`), but I did not download the full OpenAPI.

## 3. Access, authentication, cost, sandbox, rate limits, and terms for third-party tools

### Takeaway
**Slant 3D**: bearer API keys (`sl-…`) created in its dashboard, at most 3 keys, 100 requests per minute, no documented sandbox. **3DAPI**: self-serve integrator sign-up with scoped `x-api-key` keys and "connected app" scopes, 500 per minute overall and 60 per minute for writes, no sandbox but $15 of sample credit after approval, and a human review of 10 sample files before approval. **Shapeways**: OAuth2 apps and free access. **Xometry**: partner-only, by email. In all three self-serve cases, each PartCAD user could use their own key or account.

### Cited Findings
- **Slant 3D auth**:
  - Authentication is `Authorization: Bearer sl-******`. The security schemes are `ApiKeyAuth` (http bearer) and `SessionAuth` (cookie).
  - `POST /apiKey` creates keys, with a maximum of 3 API keys.
  - The rate limit is 100 requests per minute.
  - `ownerId` ("Your application's user ID") lets one integrator account partition files and orders by end user.
  - **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- **Slant 3D cost**: Older coverage describes API access as free to set up, with charges only when parts are ordered, and calls the API beta. **(trade press, 2023–24, may be dated)** — [3DPrint.com](https://3dprint.com/308580/slant-3ds-api-opens-democratizes-3d-printer-farms/); [3Printr beta launch](https://www.3printr.com/slant-3d-launches-beta-phase-for-3d-printing-api-1870594/)
- **3DAPI accounts**:
  - Integrators sign up with an email that has no seller account; "one account cannot be both".
  - Before approval, 3DAPI reviews 10 sample files, which takes 24–48 hours.
  - "There is no sandbox or test card". After approval you get $15 of sample credit valid for 30 days.
  - Every order needs business billing details (a sole trader with a tax registration is enough).
  - **(primary)** — [3DAPI business guide](https://public-api.dapi.digital/docs/guides/integrator-business.md); [3DAPI file requirements](https://public-api.dapi.digital/docs/guides/file-requirements.md)
- **3DAPI auth**:
  - Keys go in the `x-api-key` header and are scoped (`quotes:write`, `orders:write`, `wallet:read`, `webhooks:read`, and others).
  - The docs mention "a connected app, the scopes the user approved", which implies a delegated or OAuth-style flow for third-party apps.
  - The guidance says "Never put a key in browser or mobile code".
  - **(primary)** — [3DAPI authentication](https://public-api.dapi.digital/docs/guides/authentication.md)
- **3DAPI rate limits**: 500 requests per minute per key, plus 60 per minute for quote, upload, order and money operations. Catalogue and shipping reads are limited to 120 per minute per IP. A 429 response carries `Retry-After`. **(primary)** — [3DAPI rate limits](https://public-api.dapi.digital/docs/guides/rate-limits.md)
- **Shapeways**:
  - The quick-start says the API "uses OAuth 2.0 to authenticate users" and that you create an app to get keys. **(primary)** — [Shapeways quick start](https://developers.shapeways.com/quick-start)
  - A third-party transcription lists client credentials for single-account apps and authorization code with refresh token for multi-user apps. **(secondhand)** — [apis.io Shapeways](https://apis.io/apis/shapeways/shapeways-models-api/)
- **Sculpteo**: Access is "free for partners, who pay only for the printing", and partners must contact Sculpteo for access. The Upload and Order APIs require a design-provider or partner account. **(primary page via search summary; the page returned 403 to direct fetch)** — [Sculpteo API services](https://www.sculpteo.com/en/services/api-services/); [Sculpteo blog 2016](https://cdn2.sculpteo.com/blog/2016/03/01/api-update-introducing-our-new-testing-platform/)
- **Xometry**: Access is partner-only, by request to support@xometry.com, and offers need Approved or PIP partner status. **(primary)** — [Xometry Getting Started](https://developer.xometry.com/docs/getting-started); [Xometry llms.txt](https://developer.xometry.com/llms.txt)
- **Markforged Eiger**: Only the organisation admin can create keys, and access is included with Eiger Fleet. — [Eiger API spec](https://www.eiger.io/developer/spec)

### Inferences
- For Slant 3D and 3DAPI, a PartCAD user could create their own account and key and paste it into PartCAD's user config. That matches the "user's own credentials" model. 3DAPI's onboarding review of 10 sample files is a real hurdle for a casual user.
- I found no explicit terms-of-service clause on third-party open-source clients for any provider. Slant's 3-key cap and per-account platform cap are harmless for a single user.

### Gaps
- I could not find an affiliate or revenue-share program for an open-source tool from any provider. 3DAPI's checkout mode lets an integrator earn a margin on `unit_sales_price`, which is a form of revenue share, but it needs business registration.
- I found no published Slant 3D terms on API use by third-party tools, and no published API pricing.

## 4. Payment flow

### Takeaway
**Slant 3D** charges the account's payment method via Stripe when a draft order is "processed". Its public MCP server instead returns a hosted payment link. **3DAPI** offers a wallet with a saved card for the integrator, or a hosted 3DAPI checkout page where 3DAPI is merchant of record. **Shapeways** charges "the credit card you have on file".

### Cited Findings
- **Slant 3D**:
  - `POST /orders/{publicOrderId}` is described as "Process a draft order to begin production and charge payment".
  - The draft takes an optional `customer.publicPaymentServiceId` ("Customer payment ID for direct billing").
  - `GET /platforms/stripe/public-key` exposes the Stripe public key.
  - **(primary)** — [Slant 3D OpenAPI spec](https://slant3dapi.com/v2/api/openapi.json)
- **Slant 3D MCP**: `quote_checkout` "creates a payment link"; after payment the order goes to the farm. — [Slant 3D MCP server](https://www.slant3d.com/mcp-server)
- **3DAPI wallet mode**: You pay the production price plus shipping from your wallet, and any shortfall is charged to the saved card. There is no monthly fee or minimum. **(primary)** — [3DAPI business guide](https://public-api.dapi.digital/docs/guides/integrator-business.md)
- **3DAPI checkout mode**:
  - The customer pays on a hosted 3DAPI checkout page, by card in USD; "3DAPI is the merchant of record" (3DAPI Inc.).
  - The link expires after 24 hours.
  - The card fee is 2.9% + $0.30 outside the EU and UK.
  - VAT is added for EU and UK buyers, and there is no US sales tax.
  - **(primary)** — [3DAPI business guide](https://public-api.dapi.digital/docs/guides/integrator-business.md)
- **Shapeways**: The order payment method is `credit_card`, meaning "use the credit card you have on file with Shapeways". **(primary)** — [Shapeways API docs](https://developers.shapeways.com/docs)
- **OSH Cut**: Offers net-30 terms to active customers through the web only. **(primary)** — [OSH Cut FAQ](https://oshcut.com/faq)

### Inferences
- Slant 3D, 3DAPI wallet mode and Shapeways all fit PartCAD's `order(cart_id)` model with no browser redirect, as long as the user has a card on file in that service's dashboard.
- 3DAPI checkout mode and the Slant MCP payment link would fit a "return a checkout URL" variant instead.

### Gaps
- I did not find documentation of exactly how a Slant API account stores the card (dashboard setup) or what happens when payment fails at process time. The `payment.failed` event exists.

## 5. Existing third-party integrations and open-source clients

### Takeaway
Slant 3D has the most community code: several small unofficial clients (PHP, TypeScript), an unofficial OpenAPI spec (from before the official one), a mock server, an AutoGPT block and an MCP adapter. Shapeways has official clients in Python, Node, Go and PHP that have not been touched since 2023–24. Sculpteo, Xometry and 3DAPI have essentially none.

### Cited Findings
- **Slant 3D community code** — [GitHub search](https://github.com/search?q=slant3d&type=repositories)
  - Unofficial PHP client `deltafactory/slant3d-api-php` (2024).
  - TypeScript package `RichardMcQuiston01/slant3d-api-ts` (updated 2026-11-04).
  - Unofficial OpenAPI spec `NateXVI/slant3d-api-spec` (2024).
  - Mock server `justinluttrell/mock-slant-pod` (2026), which "simulates full order flow, webhooks".
  - Shopify connector `d-wald/shopify-slant3d`.
  - `nimbus-flight/thingiverse-to-slant3d`.
- **Slant 3D in other projects**: The AutoGPT project merged a "Slant 3D printing via API" block (PR #8805). The MetaForge MCP has a Slant 3D quoting adapter (PR #1235). — [AutoGPT PR #8805](https://github.com/Significant-Gravitas/AutoGPT/pull/8805); [AutoGPT Slant3D docs](https://agpt.co/docs/integrations/block-integrations/filament); [MetaForge PR #1235](https://github.com/FidelOdok/MetaForge/pull/1235)
- **Shapeways official clients**: `Shapeways/shapeways-api` (40 stars, updated 2024-10), `Shapeways/python-shapeways` (updated 2023-08), `node-shapeways`, `go-shapeways` and `php-shapeways`. — [GitHub: Shapeways/shapeways-api](https://github.com/Shapeways/shapeways-api); [GitHub: python-shapeways](https://github.com/Shapeways/python-shapeways)
- **Ponoko clients** (historical): `Ponoko/ponoko` (Ruby, 2023) and `Neon22/Ponoko-API-from-python` (2014). — [GitHub: Ponoko/ponoko](https://github.com/Ponoko/ponoko)
- **3DAPI**: ships its own MCP server, `@dapi-digital/mcp`, and a Claude Desktop extension. No community clients were found on GitHub. **(primary)** — [3DAPI llms.txt](https://public-api.dapi.digital/docs/llms.txt)

### Inferences
- An official, machine-readable spec plus a public mock server makes Slant 3D the cheapest to build and test a PartCAD plugin against without spending money.

### Gaps
- The GitHub search was by name only. I did not check whether any client implements a full quote-and-order flow end to end.

## 6. Company health and shipping geography

### Takeaway
Slant 3D is US-only in production (Boise, plus Texas and a planned Louisville farm) and raised its first round in April 2025. 3DAPI ships worldwide from US and EU partners. Shapeways was rebuilt as a Dutch B2B company after bankruptcy. Sculpteo is now owned by 3D Prod (France). Quickparts has been an independent, private-equity-owned company since 2021. Big US bureaus remain healthy but closed to third-party buyer APIs.

### Cited Findings
- **Slant 3D**:
  - Announced its first investment round in April 2025. It runs farms in Boise and Texas and plans one in Louisville. **(trade press)** — [Fabbaloo](https://www.fabbaloo.com/?p=229681)
  - The API page cites "1000 3D Printers"; other pages say "thousands". Teleport ships 95% of orders in 1–3 days. — [Slant 3D API page](https://www.slant3d.com/slant-3d-printing-api)
  - Shipping coverage is inconsistent across Slant pages: "international shipping" for API fulfilment versus farms in the US shipping domestically for Batch. — [Slant 3D API page](https://www.slant3d.com/slant-3d-printing-api)
- **3DAPI**: Delivers "worldwide except Russia, Belarus, Iran and Syria", from the production centre nearest the buyer. Import duties are paid by the buyer when shipped cross-region. **(primary)** — [3DAPI business guide](https://public-api.dapi.digital/docs/guides/integrator-business.md)
- **Shapeways**: Chapter 7 in July 2024, relaunched in Eindhoven in December 2024, B2B focus. — [cadmore.com](https://cadmore.com/blog/what-happened-to-shapeways)
- **Sculpteo**: BASF kept Sculpteo after Forward AM's 2024 insolvency (Forward AM's assets went to Stratasys). It was later sold to 3D Prod. — [TCT Magazine](https://www.tctmagazine.com/explained-why-3d-prod-sculpteo-have-merged/); [TCT: Stratasys acquires Forward AM assets](https://www.tctmagazine.com/additive-manufacturing-3d-printing-news/stratasys-acquires-forward-am-technologies-assets/)
- **Quickparts**: Sold by 3D Systems to Trilantic North America for $82M and independent since September 2021. It later acquired Xcentric Mold & Engineering. — [3DPrint.com](https://3dprint.com/285210/3d-systems-finalizes-sale-of-on-demand-business-will-operate-as-quickparts/); [3DPrint.com: Xcentric](https://3dprint.com/294590/quickparts-expands-manufacturing-capabilities-with-xcentric-mold-engineering-acquisition/)
- **Xometry**: Added auto-quote for injection molding in October 2025, according to a press-wire headline. — [FinancialContent / GlobeNewswire](https://www.financialcontent.com/article/gnwcq-2025-10-23-xometry-introduces-auto-quote-capability-for-injection-molding-services-expanding-its-digital-manufacturing-platform)
- **Protolabs**: Launched the ProDesk AI quoting platform in 2026. — [Protolabs press release](https://protolabs.gcs-web.com/news-releases/news-release-details/protolabs-introduces-prodesk-ai-enabled-manufacturing-platform)
- **Bambu**: Locked down third-party cloud writes with its 2025 security changes. — [Bambu blog](https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect)

### Inferences
- For a US-centred plugin with a durable API, Slant 3D is the strongest single candidate.
- 3DAPI is the strongest candidate for STEP input and international shipping. It is a network marketplace with partner farms rather than a single direct manufacturer, so it sits on the boundary of the "direct manufacturer" scope.
- Shapeways' API is technically usable, but production is now in the Netherlands.

### Gaps
- I did not find 2026 funding or health news for Slant 3D, 3DAPI, SendCutSend, OSH Cut, Fictiv, RapidMade, Prototek or SyBridge.
- I did not find 3DAPI's legal domicile beyond "3DAPI Inc." on card statements and the "US and Europe" footer.
- I did not verify the Shapeways relaunch facts against a primary Shapeways press release.
