# European 3D printing service bureaus: developer APIs (status as of November 2026)

Scope: direct manufacturers based in Europe (not marketplaces), judged on whether a third-party open-source tool (the PartCAD `manufacturer` plugin: `caps` / `quote` / `order`, with each user logging in with their own credentials) can integrate with them. Research done 2026-11-22. Where I fetched a primary page or spec myself, I say "verified". Claims seen only in search snippets or trade press are marked as such. Several sites (sculpteo.com, xometry.eu, makerverse.com, beamler.com, fabrikado.com, 3dactivation.be) blocked or timed out on direct fetches from this environment, so those entries rely on search-indexed copies of the pages.

## Q1. Which European bureaus have a public, documented API today?

### Takeaway
Two European direct manufacturers have a usable, documented ordering API in late 2026. **Materialise OnSite** (Belgium) publishes an OpenAPI/Swagger spec that anyone can read, but access is granted by application. **Shapeways** (relaunched and run from Eindhoven, NL) has a self-serve developer portal with OAuth2. **Sculpteo** (France) still advertises an API with upload, price and order docs, but you must contact them for access and payment is by invoice only. i.materialise's historical "Print API / Tool API" is **dead**. Protolabs, Xometry (buyer side), Weerg, Laserhub, Beamler, Prodartis, Fabrikado and Makerverse show **no public buyer API**.

### Cited Findings

**Materialise OnSite (Leuven, Belgium) — LIVE API, public spec, access on application**
- The OnSite API is a modular REST/JSON API with OAuth 2.0. To use it you must "enable the API integration option for your active OnSite account" by emailing onsite@materialise.com with subject "API". An account manager then agrees the integration terms, and the Client ID and Client Secret appear in the user's OnSite account under API settings. Verified. — [OnSite Help: Summary API Documentation](https://onsite.helpjuice.com/api-connection/summary-api-documentation)
- Base URL `https://api.onsite.materialise.com/v1`. Interactive Swagger docs are at `https://api.onsite.materialise.com/documentation/index.html`. Verified. — [OnSite Help: Summary API Documentation](https://onsite.helpjuice.com/api-connection/summary-api-documentation)
- **The OpenAPI (Swagger 2.0) spec is publicly downloadable without auth** at `https://api.onsite.materialise.com/documentation/v1/swagger.json`. It is titled "OnSite Api v1", and its security scheme is OAuth2 `application` (client-credentials) flow, token URL `https://auth.onsite.materialise.com/connect/token`, scope `API`. Verified by fetching the JSON on 2026-11-22. — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json)
- Endpoints in the spec, all verified:
  - `POST /v1/models` (multipart file upload)
  - `GET /v1/models/{id}/status`, where status is one of Created, InProcess, Processed, ProcessFailed
  - `GET /v1/models/{id}`, returning dimensions in mm, volume in cm3 and surface area in cm2
  - `GET /v1/technologies`, returning a nested technology → materials → finishings → colors tree with UUIDs
  - `POST /v1/products`, which takes modelId, technologyId, materialId, finishingId, colorId, keepPartOrientation and doNotHollow
  - `GET /v1/products/{id}/services` (Default, FastLane)
  - `POST /v1/products/{id}/price`, which takes quantity and currency and returns unitPrice, totalPrice and leadTimeDays per service
  - `POST/GET/DELETE /v1/quotations`, `POST /v1/quotations/{id}/items`, `DELETE /v1/quotations/{id}/items/{itemId}` and `POST /v1/quotations/{id}/addresses`
  - `POST /v1/delivery-addresses`, which takes company, address lines, city, zip, state, countryIsoCode, names and phone
  - `POST /v1/quotations/{id}/order`

  — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json)
- The `Money` type's currency enum is **EUR, USD, GBP, PLN**. `QuotationDetails` returns partsPrice, **transportCost**, discount, minimumOrderValue, **vat**, **totalPrice**, estimatedShipmentDate, quotationStatus and **trackingNumber**. Verified. — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json)
- Documented order flow:
  1. Get a token.
  2. Upload the model.
  3. Get technologies.
  4. Create a product.
  5. Check services.
  6. Price the product ("already with 10% online discount").
  7. Create a quotation, with currency EUR/USD/GBP/PLN and your reference ID.
  8. Add items.
  9. Create a delivery address.
  10. Attach the delivery and invoice addresses. The invoice address ID must be created manually in the OnSite profile.
  11. `POST quotations/{id}/order`.

  "Placing an order via API requires invoice payment to be enabled for your account." Each quotationID can be ordered only once. Verified. — [OnSite Help: Order Submitting Using API](https://onsite.helpjuice.com/api-connection/order-submitting-using-api)
- Accepted upload formats on OnSite: STL, 3DS, 3DM, OBJ, WRL, MATPART, **STP/STEP**, SKP, SLDPRT, CATPART, IGES, MODEL, MXP, MGX. No OnSite source lists 3MF (search snippet of OnSite help, not fetched). — [OnSite Help: accepted 3D file formats](https://onsite.helpjuice.com/en_US/accepted-3d-file-formats)
- The spec's upload 400 error says "The file extension is not supported…". 413 covers file size. Verified. — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json)

**i.materialise (Belgium) — HISTORICAL, API retired**
- Historically, i.materialise documented:
  - pricing APIs (a price without uploading)
  - an Upload Model API
  - a "3D Print Lab Connection API", which uploads a file and returns a link to redirect the customer to i.materialise's 3D Print Lab
  - cart / checkout / order-status APIs
  - invoice APIs for white-label use
  - a sandbox environment

  (search snippets of the old docs). — [i.materialise 3D Print Lab Connection API (old URL)](https://i.materialise.com/api/docs/3d-print-lab-connection-api); [i.materialise api-dokuwiki (old URL)](https://i.materialise.com/api-dokuwiki/doku.php)
- i.materialise merged into Materialise OnSite. Orders and the shop feature stopped on **31 October 2025**, and there is no shop feature on OnSite. — [VoxelMatters, 2025-10-02](https://www.voxelmatters.com/i-materialise-merges-into-materialise-onsite-3d-printing-service/); [Fabbaloo](https://www.fabbaloo.com/news/i-materialise-to-cease-orders-by-october-31-as-materialise-consolidates-3d-print-services)
- Accounts stayed read-only until 31 March 2026. Since 1 April 2026, accounts and uploaded models are no longer accessible (search snippet of a Materialise help page). — [OnSite Help: i.materialise account after closure](https://onsite.helpjuice.com/en_US/can-i-still-access-my-imaterialise-account-and-models-after-the-platform-closure)
- **Verified:** on 2026-11-22 these return HTTP 404: `i.materialise.com/api`, `/api/docs/3d-print-lab-connection-api`, `/api/docs/order-status-api` and `/api-dokuwiki/doku.php`. `i.materialise.com/en/Getting-Started` redirects to `materialise.com/.../online-3d-printing?origin=imaterialise`. The old API is gone; OnSite's API is its successor.

**Shapeways (Eindhoven, NL; relaunched) — LIVE, self-serve API**
- The developer portal `developers.shapeways.com` is live. It covers:
  - model upload with instant printability checks
  - material info
  - order placement and status
  - shipping options

  "API access is free. Get in touch to talk about volume discounts." It links code examples at `github.com/Shapeways/shapeways-api`. Verified. — [Shapeways Developers](https://developers.shapeways.com/)
- Auth is OAuth 2.0. Any registered Shapeways account can create an app (Client ID and Secret) under "Manage apps". There are two flows:
  - client_credentials, for the app owner's own account
  - **authorization_code with redirect URI**, so that "any user [can] authorize access to their Shapeways accounts" ("e.g. a plugin for Shopify… Etsy")

  An `oob` redirect URI is supported for desktop/CLI use. Tokens expire in 3600 s and a refresh token is issued. Token URL `https://api.shapeways.com/oauth2/token`. Verified. — [Shapeways Developers: Getting started](https://developers.shapeways.com/quick-start)
- API reference, verified:
  - `GET /materials/v1` and `/materials/{id}/v1`: title, supportsColorFiles, printerId, swatch, restrictions
  - `POST /models/v1`: JSON body with base64 `file`, `fileName`, `uploadScale` (required for .stl/.obj/.vox), `hasRightsToModel` and `acceptTermsAndConditions`. It returns modelId and per-material `price` and printability.
  - `GET /models/{id}/v1`
  - `GET /cart/shipping-options/v1?country=XX&zipCode=`: price "without tax in USD", plus inTransitDaysMin and inTransitDaysMax
  - `POST /orders/v1`: shipping address; items of modelId, materialId and quantity; paymentMethod `credit_card`; shippingOption Cheapest or Fastest; manufacturingSpeed Economy or Priority; refNumber
  - `GET /orders/v1` and `/orders/{id}/v1`: status counts, target ship and delivery dates, carrier, trackingNumber, trackingLink

  — [Shapeways API reference](https://developers.shapeways.com/api-reference)
- Payment: "Placed orders will be charged to the credit card on file for this Shapeways account." Transaction fees: "Contact us". Verified. — [Shapeways Developers: Placing orders](https://developers.shapeways.com/quick-start)
- Accepted upload formats per the current support centre: DAE, OBJ, STL, X3D/X3DB/X3DV, WRL, **3MF, STP, STEP**. Files must be under 100 MB and under 1M polygons (search snippet). — [Shapeways support: upload limitations](https://support.shapeways.com/hc/en-nl/articles/17001579812252-What-are-the-upload-limitations); [Shapeways support: How to upload](https://support.shapeways.com/hc/en-nl/articles/17000648918300-How-to-upload-your-3D-model)

**Sculpteo (Villejuif, France) — API advertised, contact required**
- Sculpteo's API page says it can automate order submission, upload files, retrieve instant quotes, manage the cart and track production and shipping. It says "access to the API is free for our partners", with "contact us to get access and documentation" (search snippet). The page was dated roughly mid/late 2025 by the search engine. — [Sculpteo API services](https://www.sculpteo.com/en/services/api-services/)
- The developer docs, seen via search-indexed copies because direct fetch returned Cloudflare 403, describe:
  - upload by a single multipart POST (`file`), "a single file in one of our supported 3D formats", or a "web2web" upload where Sculpteo fetches from a URL (needs a **provider account**)
  - price via `GET …price_by_uuid` with a design UUID and optional currency (**EUR, USD, GBP**)
  - order via POST to a store order URL with **login and password**, items as UUID, quantity, scale, unit and material

  "The only payment method available so far is invoice payment… you must contact us first so that the corresponding account is allowed to perform invoice payments." Shipping defaults to cheapest. — [Sculpteo dev: Ordering designs via API](https://www.sculpteo.com/en/developer/webapi/order/order/); [Sculpteo dev: Obtaining the price](https://www.sculpteo.com/en/developer/webapi/order/price/); [Sculpteo dev: Direct upload](https://www.sculpteo.com/de/developer/webapi/upload/direct/); [Sculpteo dev: Web2web upload](https://www.sculpteo.com/de/developer/webapi/upload/web2web/)
- Sculpteo had a sandbox/testing platform. A 2016 blog post is titled "API Update: Introducing our new testing platform"; its current status is unknown. — [Sculpteo blog 2016](https://cdn2.sculpteo.com/blog/2016/03/01/api-update-introducing-our-new-testing-platform/)
- Accepted formats (help centre, verified): .3DM, .3DS, .3MF, .CATPART, .DAE, .DXF, .IAM/.IPT, .IGES, .OBJ (implied), .PLY, .SAT, .SCAD, .SLDPRT/.SLDASM, **.STEP**, .X_T, .ZIP and more. STL and OBJ are recommended. — [Sculpteo help: supported formats](https://learn.sculpteo.com/en/what-are-the-file-formats-supported-by-sculpteo-for-3d-printing-1)

**Protolabs (incl. Protolabs Europe) — no public API**
- A third-party vendor (Supergood, which sells unofficial API wrappers, so it is not neutral) says Protolabs has "no public API and no developer portal". It says the developer, docs and api subdomains do not resolve, and that quoting, DFM, orders and tracking stay inside the ProDesk web app. Unverified, secondary. — [Supergood API report card: Protolabs](https://supergood.ai/api-report-card/protolabs)
- Protolabs launched **ProDesk** (an AI quoting/DFM web platform) in March 2026. — [Metal AM](https://www.metal-am.com/?p=115149); [Digital Engineering 24/7](https://www.digitalengineering247.com/article/protolabs-introduces-prodesk-ai-enabled-manufacturing-platform/additive-manufacturing)
- The only integration found is a historical Autodesk Fusion 360 quoting integration (injection molding and CNC). — [Autodesk Fusion blog](https://www.autodesk.com/products/fusion-360/blog/proto-labs-online-quoting-services-are-now-available/)

**Xometry / Xometry Europe — API is supplier-side only**
- `developer.xometry.com` (v0.1 and v0.2) exposes "Accepted Jobs (Details, Part Files…)", "Job / Line Item Statuses" and "Job Board Offers (requires additional approval)". It is for manufacturing **partners**. Access is by email with "Partner Name and business email". Verified; **no buyer quote or order endpoint is documented**. — [Xometry Developer API: Getting Started](https://developer.xometry.com/docs/getting-started)
- Buyer-side quoting is embedded through "Xometry Everywhere" (Thomasnet, 1688.com, enterprise procurement) and CAD add-ins for Fusion and Onshape. These are not an open API. — [Digital Engineering 24/7](https://www.digitalengineering247.com/article/xometry-unveils-xometry-everywhere/products); [Xometry Onshape app](https://www.xometry.com/resources/blog/introducing-the-xometry-onshape-app)
- A comparison site claims Xometry offers a "public API for programmatic quote and order workflows". This contradicts the official portal and is **unverified**. — [otronatlas](https://www.otronatlas.com/price-comparison/xometry-alternatives/) vs [Xometry Developer API](https://developer.xometry.com/docs/getting-started)

**Weerg (Scorzè/Venice, Italy) — no API**
- Weerg's own `llms.txt` (manually revised 2026-09-24) describes upload → configure → instant quote → order through the web configurator. It tells agents to send users to the quoting tool for prices, and it mentions no API. It lists 28 HP MJF 5620 Pro printers and 10 Hermle 5-axis CNCs, all production in-house. Verified. — [Weerg llms.txt](https://www.weerg.com/llms.txt)
- The homepage HTML contains no developer/API link, only a WhatsApp API link. Verified by fetch. — [Weerg](https://www.weerg.com/)

**Laserhub (Stuttgart, Germany; sheet metal, CNC) — no public API found**
- Laserhub uses third-party engines internally: Werk24 (via webhooks and a Python SDK) for drawing extraction, and WICAM for price calculation. These are vendor-authored case studies and describe internal integrations, not a customer API. — [Werk24 case study](https://es.werk24.io/case-studies/laserhub); [DirectIndustry WICAM](https://www.directindustry.com/prod/wicam-technische-software/product-5998-2629867.html)
- 2019-era press said Laserhub was "considering" interfaces into order and ERP systems. No launch was found. — [marketSTEEL](https://www.marketsteel.com/news-details/laserhub-presses-ahead-with-the-digitization-of-sheet-metal-processing.html)

**Jellypipe (Switzerland) — "public API" announced 2021, no public docs**
- The December 2021 platform v3 announcement mentions a "Public API interface… to facilitate integration with ERP systems". However, Jellypipe "does not sell to customers directly; you can order only in the e-shop of one of our Solution Partners". — [Jellypipe v3 announcement](https://jellypipe.com/en/blog-news/jellypipe-platform-v3)

**Others with no API found:** Beamler (Amsterdam), Prodartis (Appenzell, CH), Fabrikado, MakerVerse (Berlin), 3D Activation (Belgium), Imprimakers (Spain), 3Descu (Romania), Intent3D.
- Beamler: listed as active, about 4 employees (2024), with online quotes. — [PitchBook](https://pitchbook.com/profiles/company/103867-75); [Crunchbase](https://www.crunchbase.com/organization/beamler)
- Prodartis: MJF/SLS service, online quote form. — [3D.directory](https://www.3d.directory/manufacturers/profile/prodartis-ag)
- Fabrikado: online shop with instant offers for cutting, 3D printing and milling/turning from quantity 1. — [Fabrikado](https://fabrikado.com/en)
- Imprimakers, 3Descu and Intent3D: web instant quotes accepting STEP. — [Imprimakers](https://imprimakers.com/en/); [3Descu](https://quote.3descu.com/); [Intent3D](https://intent3d.com/)
- 3DreamFactory (European print-on-demand) advertises "API + webhook integration scoping" after a pilot. This is per-project, not self-serve, and was seen in a search snippet only. — [3DreamFactory](https://3dreamfactory.com/print-on-demand)

### Inferences
- Only Materialise OnSite and Shapeways can be targeted by a PartCAD plugin today without a commercial negotiation that changes per user. Of the two, **only Shapeways lets an arbitrary user self-serve**: they create an app or authorize a third-party app via OAuth. OnSite requires each user's account to be API-enabled by an account manager.
- Sculpteo is technically suitable: it has upload, price, order and EUR. But a per-user "contact us + invoice payment enablement" gate makes it a partner integration, not an open one.
- The European "instant quote" bureaus (Weerg, Fabrikado, Prodartis, Imprimakers and others) all quote via web configurators only.

### Gaps
- I could not fetch Sculpteo's developer pages directly (Cloudflare 403), so I cannot confirm they are still maintained after the May 2026 3D Prod acquisition, or whether the login/password order auth has been replaced.
- I could not confirm 3D Activation's or MakerVerse's tooling; their sites timed out from this environment.
- I could not reach the `Shapeways/shapeways-api` GitHub repo (GitHub access restricted in this session), so its last-commit date is unknown.

## Q2. How do the live APIs map to PartCAD's `caps` / `quote` / `order`?

### Takeaway
Materialise OnSite maps almost one-to-one:
- `caps` is `GET /technologies`.
- `quote` is a quotation with total, VAT, transport and currency, and the quotationId serves as the cart id.
- `order` is `POST /quotations/{id}/order`.

Shapeways covers `caps` and `order` but has no server-side cart or quote object. A plugin must sum per-material model prices plus `shipping-options`, in USD and before tax. Sculpteo covers per-design price and order, with no quotation object documented in what I could see.

### Cited Findings
- **OnSite `caps`:** `GET /v1/technologies` returns technologies → materials → finishings → colors, each with a UUID and name. Upload formats are given in help docs, not in an endpoint. Verified. — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json); [OnSite accepted formats](https://onsite.helpjuice.com/en_US/accepted-3d-file-formats)
- **OnSite `quote`:**
  1. Upload the STEP. Processing is asynchronous, so poll `/models/{id}/status` until Processed.
  2. Create a product per part.
  3. Create a quotation with a currency.
  4. Add items.
  5. Create a delivery address from the user's shipping address (`countryIsoCode`) and attach it together with an invoice address ID that **must already exist in the user's OnSite profile**.
  6. `GET /quotations/{id}` returns totalPrice, transportCost, vat and minimumOrderValue as Money with currency.

  Verified. — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json); [OnSite Help: Order Submitting](https://onsite.helpjuice.com/api-connection/order-submitting-using-api)
- **OnSite `order`:** `POST /v1/quotations/{id}/order`. Each quotation can be ordered once. Status and tracking come from `GET /quotations/{id}` (quotationStatus, trackingNumber, estimatedShipmentDate). There are no webhooks in the spec. Verified. — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json)
- **Shapeways `caps`:** `GET /materials/v1` returns materials with restrictions and colour support. There are no explicit finish or format endpoints; formats are in the support docs. Verified. — [Shapeways API reference](https://developers.shapeways.com/api-reference)
- **Shapeways `quote`:**
  - Upload returns `materials{id:{price, isActive}}`. Material prices in the upload schema are described as "Price (USD)".
  - `GET /cart/shipping-options/v1` gives shipping "without tax in USD" per country and zip.
  - There is no endpoint that returns a cart total including tax, and no cart id.

  Verified. — [Shapeways API reference](https://developers.shapeways.com/api-reference)
- **Shapeways `order`:** `POST /orders/v1` takes the address, items, `paymentMethod=credit_card` and a shipping option. It returns orderId and productionOrderIds. Status comes from `GET /orders/{id}/v1`. Verified. — [Shapeways API reference](https://developers.shapeways.com/api-reference)
- **Sculpteo:** a price per design UUID (currency EUR/USD/GBP) and an order POST of items with scale, unit and material (search snippets). — [Sculpteo dev: price](https://www.sculpteo.com/en/developer/webapi/order/price/); [Sculpteo dev: order](https://www.sculpteo.com/en/developer/webapi/order/order/)

### Inferences
- For Shapeways, a PartCAD plugin would synthesize the `cart id` client-side (for example, a hash of model IDs, materials, quantities and address). It would report the total as Σ(model material price × qty) + shipping, in USD, and flag that tax and any Priority surcharge ("usually +30% per item") are excluded. There is a risk the price changes between quote and order.
- OnSite's 10% online discount is already applied in API prices. Minimum order value and VAT come back explicitly, which is ideal for an honest `quote`.
- STEP straight from PartCAD works for OnSite (STP/STEP accepted) and for Shapeways (STP/STEP listed in the current support centre). For Shapeways, STL/OBJ need `uploadScale`, so if a plugin falls back to STL it must send 0.001 for mm.

### Gaps
- No rate limits are published for OnSite or Shapeways.
- I found no OnSite or Shapeways webhook support.
- I did not determine whether Shapeways' STEP acceptance applies to the API upload path as well as the web uploader. The API doc only mentions scale requirements for .stl/.obj/.vox.

## Q3. Access model, auth, cost, sandbox, per-user credentials, third-party terms

### Takeaway
Shapeways is self-serve, free and per-user OAuth, which fits PartCAD's "each user logs in with their own credentials" exactly. OnSite uses per-account client credentials, issued only after a request to an account manager and a "terms finalised" step. Sculpteo is partner-only, with free access for partners. None of them publishes an affiliate or revenue-share programme for API integrators in what I found.

### Cited Findings
- **Shapeways:** any verified account creates apps; client_credentials or authorization_code (with `oob`); "API access is free"; transaction fees and volume discounts via contact. Verified. — [Shapeways Developers](https://developers.shapeways.com/); [Getting started](https://developers.shapeways.com/quick-start)
- **Shapeways upload terms:** each upload requires `hasRightsToModel=1` and `acceptTermsAndConditions=1`, meaning the user accepts Shapeways' T&C per upload. Verified. — [Shapeways API reference](https://developers.shapeways.com/api-reference)
- **OnSite:** email onsite@materialise.com with subject "API". "Once all integration details and terms have been finalized", the Client ID and Secret are generated in the user's account at `onsite.materialise.com/en/account/apisettings`. Verified. — [OnSite Help: Summary API Documentation](https://onsite.helpjuice.com/api-connection/summary-api-documentation)
- **Sculpteo:** "access to the API is free for our partners". Ordering requires prior contact to enable invoice payment on that account. Web2web upload needs a provider account (search snippets). — [Sculpteo API services](https://www.sculpteo.com/en/services/api-services/); [Sculpteo dev: order](https://www.sculpteo.com/en/developer/webapi/order/order/)
- **Xometry partner API:** by email request with partner name. — [Xometry Developer API](https://developer.xometry.com/docs/getting-started)
- **Sandbox:** i.materialise had one (historical). Sculpteo announced a testing platform in 2016 (current status unknown). No sandbox is documented for OnSite or Shapeways. — [i.materialise docs (old)](https://i.materialise.com/api-dokuwiki/doku.php); [Sculpteo blog 2016](https://cdn2.sculpteo.com/blog/2016/03/01/api-update-introducing-our-new-testing-platform/)

### Inferences
- With OnSite, a PartCAD plugin would ask each user for their own Client ID and Secret. The plugin cannot obtain them on the user's behalf, so onboarding includes "email Materialise and wait".
- No sandbox means plugin testing on OnSite and Shapeways must stop before `order` (quote-only tests), or use real orders.

### Gaps
- I found no published OnSite or Shapeways API terms of use specific to third-party/open-source clients, and no affiliate programmes.

## Q4. Payment flow

### Takeaway
All three live APIs settle against the user's **account**: OnSite and Sculpteo by **invoice** (which must be enabled per account), Shapeways by **credit card on file**. None uses a redirect-to-checkout URL. The only redirect-style flow found, i.materialise's 3D Print Lab Connection, is historical.

### Cited Findings
- OnSite: "placing an order via API requires invoice payment to be enabled for your account". The invoice address supports e-invoicing (`useEInvoice`, `eInvoiceEmail`), and the help centre mentions Peppol. Verified. — [OnSite Help: Order Submitting](https://onsite.helpjuice.com/api-connection/order-submitting-using-api); [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json)
- Shapeways: `paymentMethod: credit_card`, using the card saved in account settings. Verified. — [Shapeways API reference](https://developers.shapeways.com/api-reference)
- Sculpteo: "The only payment method available so far is invoice payment" (search snippet). — [Sculpteo dev: order](https://www.sculpteo.com/en/developer/webapi/order/order/)
- Historical i.materialise: the 3D Print Lab Connection API returned a link "to which your application can redirect your customers" (search snippet; page now 404). — [i.materialise (old)](https://i.materialise.com/api/docs/3d-print-lab-connection-api)

### Inferences
- PartCAD's `order` call can be fully non-interactive for all three. But for OnSite and Sculpteo it only works for business accounts with invoice terms, which effectively excludes hobbyist individual users.

### Gaps
- Whether OnSite grants invoice payment to individuals (non-companies) is not stated.

## Q5. Existing third-party integrations and open-source clients

### Takeaway
Shapeways has the richest ecosystem: a Shopify plug-in, historical TinkerCad integration and an official GitHub examples repo. For Materialise and Sculpteo, integrations are historical (i.materialise and Sculpteo were once integrated into CAD and design tools). Protolabs and Xometry integrate only via their own CAD add-ins (Fusion, Onshape), not via an open API.

### Cited Findings
- Shapeways: the portal points non-developers to "a Shopify plug-in" and links code examples at `github.com/Shapeways/shapeways-api`. The shapeways.com homepage references "Shopify, or Etsy E-commerce Integrations" (verified). In 2013 TinkerCad used the API to send designs for printing. — [Shapeways Developers](https://developers.shapeways.com/); [TechCrunch 2013](https://techcrunch.com/2013/03/07/shapeways-rolls-out-developer-portal-and-new-api-in-a-bid-for-better-3d-printing-apps)
- The relaunched Shapeways said it was working to "reintegrate e-commerce platforms like Shopify and Etsy" (Dec 2024). — [3D Printing Industry, 2024-12-10](https://3dprintingindustry.com/news/shapeways-resurges-with-founders-and-eindhoven-team-at-helm-235043/)
- Xometry: Fusion and Onshape add-ins (instant price, lead time, DFM). — [Xometry Onshape app](https://www.xometry.com/resources/blog/introducing-the-xometry-onshape-app); [Autodesk App Store](https://marketplace.autodesk.com/apps/2a94bf7d-3e13-4095-a6b5-9a6c36a9803d)
- Protolabs: Fusion 360 quoting (historical). — [Autodesk Fusion blog](https://www.autodesk.com/products/fusion-360/blog/proto-labs-online-quoting-services-are-now-available/)
- Sculpteo launched its public API around 2015, aimed at website and app integrators. — [3DPrint.com](https://3dprint.com/63648/sculpteo-launches-api/); [3D Printing Industry](https://3dprintingindustry.com/news/sculpteo-opens-its-3d-printing-cloud-engine-to-the-public-48595/)

### Inferences
- No open-source OnSite client was found. A PartCAD plugin would likely be the first public one, and it could be generated from the public swagger.json.

### Gaps
- I did not search GitHub exhaustively (GitHub API access was restricted in this session). Community clients for Shapeways and Sculpteo (for example, old Python wrappers) were not enumerated.

## Q6. Company health, deprecations, shipping region, currency

### Takeaway
The European landscape consolidated heavily in 2024–2026:
- i.materialise was folded into OnSite and its API retired.
- Shapeways went bankrupt in July 2024 and was rebought by its founders, run from Eindhoven. Manuevo now redirects to shapeways.com.
- Sculpteo left BASF and was bought by France's 3D Prod in May 2026.
- Forward AM (BASF's spin-out) went insolvent and its assets went to Stratasys, without Sculpteo.

### Cited Findings
- Shapeways history:
  - It filed for bankruptcy in July 2024.
  - In August 2024, Manuevo BV bought the Dutch subsidiary's assets (Eindhoven plant, 30 of 53 jobs kept). Manuevo said existing Shapeways customers "should soon be able to re-establish their APIs" and that it serves US, UK and EU customers.
  - In December 2024, WVS International / Manuevo BV acquired the Shapeways brand and website, and the founders Vogelaar (CEO) and Schouwenburg (CTO) relaunched it.

  — [3D Printing Industry, Aug 2024](https://3dprintingindustry.com/news/shapeways-relaunched-in-europe-as-manuevo-following-asset-acquisition-232193/); [3D Printing Industry, 2024-12-10](https://3dprintingindustry.com/news/shapeways-resurges-with-founders-and-eindhoven-team-at-helm-235043/)
- Verified: `www.manuevo.com` now redirects to `www.shapeways.com`. — [Shapeways](https://www.shapeways.com/)
- In June 2025 Shapeways signed a long-term lease for a new Eindhoven facility (Strijp-T); 2025 relaunch phases included Thangs print-on-demand. — [Fabbaloo](https://www.fabbaloo.com/news/revived-shapeways-prepares-for-future-growth-with-new-high-capacity-site); [TCT](https://www.tctmagazine.com/shapeways-launches-early-access-to-thangs-print-on-demand/)
- Sculpteo: acquired by 3D Prod (Raon-l'Étape, France) and announced 18 May 2026, ending BASF ownership since 2019. Sources say customers keep "the same trusted Sculpteo experience and digital tools". Sources differ on the exact date (7 vs 18 May). — [3D Printing Industry](https://3dprintingindustry.com/news/3d-prod-and-sculpteo-merge-to-scale-am-in-france-251695/); [TCT](https://www.tctmagazine.com/3d-prod-and-sculpteo-announce-merger/); [Sculpteo blog 2026-05-25](https://www.sculpteo.com/blog/2026/05/25/sculpteo-joins-the-3d-prod-group-to-form-the-new-european-leader-in-3d-printing/)
- Forward AM (Sculpteo's intended parent) filed for insolvency at the end of 2024, and Stratasys acquired its assets. Sculpteo stayed with BASF New Business until the 3D Prod deal. — [TCT](https://www.tctmagazine.com/stratasys-acquires-forward-am-technologies-assets/); [Fabbaloo](https://www.fabbaloo.com/news/3d-prod-acquires-sculpteo)
- BASF shut down Sculpteo's online design **marketplace** in 2023. That was the designer storefronts, not the manufacturing API. — [3DPrint.com](https://3dprint.com/304058/basf-to-shut-down-sculpteos-online-3d-printing-marketplace/)
- Materialise OnSite currencies: EUR, USD, GBP, PLN. Shapeways API prices are in USD. Sculpteo uses EUR, USD and GBP. — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json); [Shapeways API reference](https://developers.shapeways.com/api-reference); [Sculpteo dev: price](https://www.sculpteo.com/en/developer/webapi/order/price/)
- Weerg ships across Europe (48 h Italy, 72 h Europe, per its marketing). — [Weerg CNC page](https://www.weerg.com/cnc-machining-online-service)
- Laserhub's last disclosed round was Series B, June 2022. — [Crunchbase](https://www.crunchbase.com/organization/laserhub)

### Inferences
- Shapeways' API is the old v1 surface (same endpoint shapes as before the bankruptcy) brought back under Eindhoven management. The docs even contain an internal `…dev-cluster.ehv.shapeways.net` URL ("ehv" = Eindhoven) in a curl example, which suggests they are maintained by the Eindhoven team. This is an inference, not a stated fact.
- Given the ownership churn, PartCAD plugins for these services should expect API changes and keep provider-specific code isolated in the plugin repo, which matches PartCAD's out-of-tree plugin model.

### Gaps
- Countries each API will ship to was not enumerated. OnSite takes any `countryIsoCode`, but its serviced country list was not found. Shapeways' shipping-options endpoint is per country.

## Q7. Bureaus out of scope, or reachable only via quoting software

### Takeaway
Several names on the list are not European direct manufacturers: FacFox, Unionfab, JawsTec and Xometry. MakerVerse and Craftcloud are platforms or marketplaces. Most European bureaus without an API quote through in-house configurators. I found no specific confirmed DigiFabster/3YOURMIND/Paperless/AMFG deployments for the named bureaus in this pass; that platform layer is covered by another researcher.

### Cited Findings
- Unionfab is described as an on-demand manufacturer based in China (secondary source, a competitor's listicle). — [Unionfab blog](https://www.unionfab.com/blog/2025/09/xometry-competitors); [MakerVerse listicle](https://www.makerverse.com/resources/insights-and-trends/the-10-best-xometry-alternatives-in-2026/)
- MakerVerse is a Berlin-based digital manufacturing platform, i.e. a network rather than a single factory (secondary). — [MakerVerse](https://www.makerverse.com/resources/best-cnc-machining-services-europe/)
- FacFox offers web Auto Quote / Manual Quote, and no API was found. — [FacFox](https://facfox.com/)
- JawsTec's only relevant page is a blog about AI instant quoting; no API. — [JawsTec](https://www.jawstec.com/ai-powered-instant-quoting/)
- Craftcloud (All3DP, Munich) is a marketplace of more than 150 services; no official API docs were found. — [All3DP: Craftcloud explained](https://all3dp.com/1/craftcloud-by-all3dp-simply-explained/)
- Quote3D sells a REST quoting API for storefronts that accepts STEP up to 50 MB. It is software, not a manufacturer. — [Quote3D](https://quote3d.com/en)

### Inferences
- From my general knowledge (not verified this session): FacFox is Shenzhen-based and JawsTec is US (Arizona)-based. Neither is European.

### Gaps
- Which specific European bureaus run DigiFabster, 3YOURMIND, Paperless Parts or AMFG front-ends was not established here.
- 3D Activation's quoting stack is unknown; its site was unreachable.
- I found no Polish or Nordic bureau with a public API. Spain's Imprimakers and Romania's 3Descu have web quotes only.
