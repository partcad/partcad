# How a user authenticates to the API-friendly 3D printing services (Craftcloud, Slant 3D, 3DAPI, Materialise OnSite, Shapeways, Treatstock, JLC3DP), as of 22 November 2026

Method: these notes extend `research_notes/3D printing service APIs for PartCAD/` and do not repeat what those notes settled. Unless marked otherwise, every finding marked "probed" comes from a direct, unauthenticated HTTP GET made from this session on 2026-11-22. That covers specs, health checks, public catalogues, OAuth discovery documents, help pages and the web apps' JavaScript bundles. No account was created, no order was placed and no personal data was sent. One attempt to call Craftcloud's anonymous upload-initiate endpoint (a POST that creates a server-side record) was blocked by this session's permission policy and was not retried. Craftcloud's upload behaviour therefore rests on its help centre and on third-party code. "Secondhand" marks claims taken from third-party code or blogs. "Inference" marks conclusions drawn here.

## Q1. How does a user get a credential for each service, and can one open-source client serve every user?

### Takeaway
Only two services give users self-serve credentials with no human in the loop. **Slant 3D** issues a dashboard key (`sl-…` bearer). **Shapeways** lets users register an OAuth app. **3DAPI** also has a self-serve dashboard key, but only after a 24–48 h human review of 10 sample files. It also runs a standards-compliant OAuth server, but only for its MCP endpoint. **Materialise OnSite** issues client-credentials pairs only after an email and an agreement with an account manager. **Treatstock** and **JLC3DP** issue partner credentials on request or application. **Craftcloud** needs no credential at all to quote or order.

Only one service offers user-delegated OAuth that suits a CLI with one client identity shared by every user: 3DAPI's MCP authorization server (PKCE, public clients, dynamic client registration and client-ID metadata documents). Shapeways' OAuth needs a client secret at the token exchange. OnSite's identity server supports only `client_credentials`.

### Cited Findings

**Craftcloud**
- The live spec declares no security scheme: `securityDefinitions: {}`. Only `PATCH /v5/payment/net30/{paymentId}/settle` carries `basicAuth`. Probed — [Craftcloud spec](https://api.craftcloud3d.com/api-docs.json)
- A Craftcloud account is optional. Account holders get an order dashboard, a model library and a "Refer a Friend" 10% code. Orders placed before an account was created can be attached on request. Help article modified 2026-10-26 — [Craftcloud: benefits of an account](https://support.craftcloud3d.com/en/articles/211-what-are-the-benefits-of-creating-a-craftcloud-account)
- `POST/GET /v5/referral` answered `401 Unauthorized` without credentials. A third-party adapter concluded that "a voucher code belongs to a logged-in Craftcloud account, not a server API key" (secondhand, verified by its author 2026-10-13) — [three.ws craftcloud adapter](https://github.com/nirholas/three.ws/blob/HEAD/api/_lib/print/adapters/craftcloud.js)
- Kiln's development log reports that "Craftcloud replied to our partner email": public endpoints (upload, price, cart, order) work without an API key, and `KILN_CRAFTCLOUD_API_KEY` "is only needed to associate orders with a Craftcloud account" (secondhand; the key's issuance and header name are not documented anywhere I could reach) — [Kiln COMPLETED_TASKS.md (mirror)](https://github.com/LeoYeAI/agent-master-skills/blob/HEAD/skills/kiln/COMPLETED_TASKS.md); [Kiln DEPLOYMENT.md](https://github.com/codeofaxel/Kiln/blob/HEAD/docs/DEPLOYMENT.md)
- Other open-source adapters only guess at a key. One's code comment reads "the spec declares no security scheme; Bearer is an assumption" — [akshaya-bots/receipts craftcloud.py](https://github.com/akshaya-bots/receipts/blob/HEAD/backend/receipts/craftcloud.py)

**Slant 3D**
- Sign-up is self-serve on slant3dapi.com, by email and password (with email verification and a disposable-email blocklist) or "Sign up with Google" (`/v2/auth/google`). Probed: strings in the dashboard's JS bundle — [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js)
- The docs say: "Once you have an account and are ready, you can generate your API key on the account page". The key "will only be displayed once". "You can have a maximum of 3 API Keys per account". "If you had beta access to V2 your V1 API Key will no longer be supported". Probed: docs text in the same bundle — [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js)
- Keys are managed only through a logged-in session. `GET/POST /apiKey` carry `security: SessionAuth` (cookie named `session`). Most data endpoints carry `ApiKeyAuth` (http bearer) only. Probed — [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- An unauthenticated `GET /v2/api/filaments` answers 401 `"Bearer token required in Authorization header"`. `GET /v2/api/apiKey` answers 401 `"Please log in to access this resource"`. Probed — [Slant filaments endpoint](https://slant3dapi.com/v2/api/filaments)
- The bundle's own key calls are `POST /api/apiKey {keyName}`, `PATCH /api/apiKey/{id}` (refresh/regenerate) and `DELETE /api/apiKey/{id}` (deactivate). The spec instead documents `POST /apiKey {name}`, which is a discrepancy. Probed — [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js); [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- Before drafting orders, a user also needs a **platform** (`name` plus an HTTPS `url`; at most 5 enabled) and "a connected payment method on your account" (a Stripe card added on the account page). Probed: docs text and `x-agent-hints` — [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js); [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- No OAuth or delegated flow exists: the spec has no OAuth scheme, and "oauth" does not occur in the bundle. Probed — [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json)

**3DAPI (dapi.digital)**
- Integrators sign up at `dapi.digital/integrator/sign-up`. "Your account is approved once 10 of your files are approved. Order to Quote ratio 1:1500." The email used must not belong to a 3DAPI seller account — [3DAPI quickstart](https://public-api.dapi.digital/docs/guides/quickstart.md)
- Approval is a human review "file by file, which usually takes 24 to 48 hours". An email arrives when it is done — [3DAPI: submit sample files](https://public-api.dapi.digital/docs/guides/request-integrator-approval.md)
- Keys go in the `x-api-key` header and are created on the dashboard's API keys page (`dapi.digital/integrator/api-keys`). `POST /v2/api-keys` works only "with a signed-in dashboard session: an API key cannot manage keys". The full `secret` is shown only in that response. Keys "work before your account is approved, with the same onboarding limits". Probed — [3DAPI authentication guide](https://public-api.dapi.digital/docs/guides/authentication.md); [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)
- The dashboard session is "sent as `Authorization: Bearer <token>`" and is not scoped — [3DAPI authentication guide](https://public-api.dapi.digital/docs/guides/authentication.md)
- The OAuth server for the MCP endpoint is live. `https://mcp.dapi.digital/.well-known/oauth-authorization-server` advertises:
  - `response_types_supported: ["code"]`
  - `grant_types_supported: ["authorization_code","refresh_token"]`
  - `code_challenge_methods_supported: ["S256"]`
  - `token_endpoint_auth_methods_supported: ["none"]` (public clients)
  - a `registration_endpoint` (dynamic client registration) and a `revocation_endpoint`
  - `client_id_metadata_document_supported: true`
  - scopes `read`, `write`, `money` and `offline_access`

  The protected resource is `https://mcp.dapi.digital/mcp`. An unauthenticated MCP `initialize` gets 401 with `WWW-Authenticate: Bearer resource_metadata=…`. Probed — [3DAPI OAuth metadata](https://mcp.dapi.digital/.well-known/oauth-authorization-server); [3DAPI protected-resource metadata](https://mcp.dapi.digital/.well-known/oauth-protected-resource)
- In 3DAPI's own words: "When it asks how to authenticate, choose OAuth, and leave any client ID or secret fields empty". The consent page offers "See your account" (always), "Make changes", and "Orders and purchases" (off unless ticked). Money moves are "a two-step action… nothing is charged until you confirm". Connected apps are listed and disconnected on the API keys page — [3DAPI: Connect Claude, ChatGPT or Grok](https://public-api.dapi.digital/docs/guides/connect-ai-apps.md)
- `public-api.dapi.digital` has no OAuth metadata of its own: `/.well-known/oauth-authorization-server` returns 404. Its OpenAPI declares only `apiKey` (`x-api-key`) and `session` (bearer). Probed — [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)

**Materialise OnSite**
- The OIDC discovery document reports `grant_types_supported: ["client_credentials"]` only. It has no `authorization_endpoint` and no `revocation_endpoint`. Scopes are `openid`, `API` and `crm.access`. Client authentication is `client_secret_post`, `client_secret_basic` or `private_key_jwt`. Probed — [OnSite OIDC discovery](https://auth.onsite.materialise.com/.well-known/openid-configuration)
- The spec's security definition is OAuth2 `application` flow, `tokenUrl https://auth.onsite.materialise.com/connect/token`, scope `API`. An unauthenticated `GET /v1/technologies` answers 401. Probed — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json)
- Access means emailing onsite@materialise.com with subject "API". An account manager then contacts you, and credentials are issued "Once all integration details and terms have been finalized". The page does not say whether individuals or only businesses qualify — [OnSite help: Summary API documentation](https://onsite.helpjuice.com/api-connection/summary-api-documentation)

**Shapeways**
- Registration is on the new auth host: `auth.shapeways.com/register` (and `/login`). Probed: links on the quick-start — [Shapeways quick start](https://developers.shapeways.com/quick-start)
- The app page `developers.shapeways.com/manage-apps` is live behind a login: it answered 302 to `portal.shapeways.com/login?targetUrl=/developers/manage-apps`. The old `www.shapeways.com/manage-apps` returns 404. Probed — [Shapeways manage apps](https://developers.shapeways.com/manage-apps)
- The quick start offers two models. **"Only the app owner account"** uses `client_credentials`. **"Multiple user accounts"** is the choice "if you are creating a plugin for Shopify, Squarespace, Etsy, etc that will need access to Shapeways user data other than your own". It uses `authorization_code` via `https://api.shapeways.com/oauth2/authorize?response_type=code&client_id=…&redirect_uri=…`. Every token-exchange example sends `client_secret`. **"oob"** can be added as a redirect URI, described as a quick-start for the account owner. PKCE is not mentioned. Probed — [Shapeways quick start](https://developers.shapeways.com/quick-start)
- `GET https://api.shapeways.com/oauth2/authorize?…&redirect_uri=oob` answered 302 to `api.shapeways.com/login?targetUrl=…`, so the authorize endpoint is live. `GET /oauth2/token` answered 405 (POST only). Probed — [Shapeways authorize endpoint](https://api.shapeways.com/oauth2/authorize)

**Treatstock**
- The documentation's "Get API tokens" button links to a contact form (`/site/contact?subject=API tokens request`). There are two token types. The `private-key` "provides full access to the API and should not be disclosed to users because they will then have the ability to retrieve confidential data about 3D model uploads of other users". The `public-upload-key` "is restricted to the upload of new models only". Probed — [Treatstock API documentation](https://www.treatstock.com/help/article/83-api-documentation)

**JLC3DP / JLCPCB**
- Access is by application at api.jlcpcb.com with a JLCPCB account. Approval weighs order history (established in the earlier notes). Third-party clients sign requests with HMAC-SHA256 using an app ID, an access key and a secret, in an `Authorization: JOP appid=…, accesskey=…, nonce=…, timestamp=…, signature=…` header (secondhand; the official signing spec sits behind the application) — [JLCPCB API access article](https://jlcpcb.com/help/article/jlcpcb-online-api-available-now); [Pipedream JLCPCB integration (search summary)](https://pipedream.com/apps/jlcpcb/integrations/amazon-ses); [KiCAD MCP server jlcpcb.py (search summary)](https://glama.ai/mcp/servers/@mixelpixx/KiCAD-MCP-Server/blob/d2723bc29207c942bc93083131e2ac2a8d1a82d5/python/commands/jlcpcb.py)

### Inferences
- **How each service fits `pc login`** (all inference):
  - **Slant 3D.** The one-time key appears in the "Generate New API Key" modal on `slant3dapi.com/account`. A DOM-text capture works only at that moment, so `--set api_key=sl-…` is the robust path. A neater option: capture the `session` cookie after the user signs in, then have the plugin call the session-only key-creation endpoint once to mint a PartCAD-named key, and store the key rather than the cookie. That depends on the body field (`keyName` in the bundle, `name` in the spec) and needs testing. Data endpoints reject the session cookie, so the cookie alone is not enough.
  - **3DAPI.** `--set api_key=…` works with a key the user creates with only the scopes PartCAD needs. Capturing the dashboard's bearer session token from storage and minting a key with `POST /v2/api-keys` is possible in principle. Where the dashboard keeps that token was not checked.
  - **OnSite.** `--set client_id=… --set client_secret=…`, which the user copies from `onsite.materialise.com/en/account/apisettings`.
  - **Shapeways.** Best fit: each user registers their own app and the plugin stores `client_id`/`client_secret`, minting a one-hour `client_credentials` token on every call (owner-only access, which is exactly a PartCAD user's own account). One PartCAD-wide client would mean shipping a `client_secret` in open-source code, because the token exchange requires one and PKCE is undocumented.
  - **Craftcloud.** Needs no `pc login`. Whatever "API key" Craftcloud may issue only links orders to an account. Its issuance and header are undocumented.
- **3DAPI is the only service whose OAuth suits a CLI with one shared identity.** Public clients, S256 PKCE and client-ID metadata documents mean PartCAD could publish one HTTPS client-metadata URL (or register dynamically) and run a loopback authorization-code flow, with no secret in the code. The token is scoped to the MCP resource, though, not to `public-api.dapi.digital`. Using it would make the plugin an MCP client of `mcp.dapi.digital`. That is a different transport, but it is how 3DAPI intends third-party apps to act for a user.

### Gaps
- Craftcloud's optional API key is undocumented: where it is issued, its header name (`x-api-key`, `Authorization`, other), and what it changes beyond linking an order to an account. I found no reachable primary source.
- I could not see whether Slant's account page, Shapeways' app form, 3DAPI's dynamic client registration or OnSite's API settings accept a loopback (`http://127.0.0.1`) redirect URI. That would need an account or a registration POST, which were out of bounds. Shapeways is documented to accept `oob`.
- Whether one Shapeways app may be used by many users through `oob` (rather than only by its owner) is not stated. The docs present `oob` as an owner-only shortcut.
- Whether OnSite enables API access for individuals, as opposed to companies, is not stated. Its VAT article does distinguish private clients without a VAT number, which suggests individuals can hold accounts — [OnSite VAT (search summary)](https://onsite.helpjuice.com/en_US/value-added-tax).

## Q2. Credential lifetime, refresh, rotation, revocation and scopes; can a key be limited to quoting?

### Takeaway
**3DAPI is the only service with per-key scopes that separate quoting (`quotes:*`) from ordering (`orders:write`).** Its keys do not expire and can be revoked on the dashboard. **Slant 3D** keys are unscoped, have no expiry field, and can be regenerated or deactivated (at most 3 keys). **OnSite** and **Shapeways** use one-hour-class OAuth access tokens. OnSite's lifetime is unpublished. Shapeways issues a refresh token only in the multi-user flow, which PartCAD cannot yet persist.

### Cited Findings
- **3DAPI scopes:** `quotes:read`, `quotes:write`, `orders:read`, `orders:write` ("place and cancel orders"), `orders:read_customer`, `wallet:read`, `webhooks:read`, plus per-resource designer scopes. A request outside a key's scopes gets 403 `missing_scope`. Each operation lists its accepted scopes in `x-required-scopes` — [3DAPI authentication guide](https://public-api.dapi.digital/docs/guides/authentication.md)
- 3DAPI's own operation table confirms the split:
  - `POST /v2/quotes` and `POST /v2/uploads` (purpose `quote_file`) need `quotes:write`.
  - `POST /v2/integrator/orders` and `/cancel` need `orders:write`.
  - `POST /v2/integrator/orders/shipping-estimate` needs only `orders:read`.

  Probed — [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)
- **3DAPI key lifecycle:** "Up to 10 active keys per account; revoke one to make room" (`DELETE /v2/api-keys/{id}`, session only). The key object has `created_at` and `last_used_at` and no expiry field. The `secret` (example `sk_3f9a…`) "cannot be retrieved later. If it is lost, revoke the key and create a new one." Probed — [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)
- **3DAPI OAuth:** refresh tokens via `offline_access`, plus a revocation endpoint. Probed — [3DAPI OAuth metadata](https://mcp.dapi.digital/.well-known/oauth-authorization-server). "If you connect the same app again later with the same or fewer permissions, 3DAPI does not ask a second time". ChatGPT is never given order permissions — [3DAPI connect AI apps](https://public-api.dapi.digital/docs/guides/connect-ai-apps.md)
- **Slant key lifecycle:** keys "can be regenerated at any time" (`PATCH /api/apiKey/{id}` refreshes the key). Deactivation is confirmed with "This action cannot be undone and will immediately stop all requests using this key". The UI shows only a preview (`sl-<keyPreview>****`). There is no scope or expiry field in the spec, and `x-agent-hints` says "rate-limit: 100 requests per minute". Probed — [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js); [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- **Slant usage:** `GET /usage` "to review key usage for all user keys". Probed — [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- **Shapeways tokens:**
  - `client_credentials` returns `{"access_token","token_type":"bearer","expires_in":3600}` with no refresh token.
  - `authorization_code` returns `expires_in: 3600` plus a `refresh_token`.
  - Refreshing is `grant_type=refresh_token` with `client_id` and the client secret.

  No scopes are documented. Probed — [Shapeways quick start](https://developers.shapeways.com/quick-start)
- **OnSite tokens** are "temporary authorization tokens", with no lifetime given. The token endpoint is client-credentials only, so no refresh token exists. Probed and fetched — [OnSite OIDC discovery](https://auth.onsite.materialise.com/.well-known/openid-configuration); [OnSite help: Summary API documentation](https://onsite.helpjuice.com/api-connection/summary-api-documentation)
- **Treatstock:** two fixed token types (full `private-key`, upload-only `public-upload-key`). Limits are concurrent connections per key: 7 GET, 15 POST, 30 PUT. Probed — [Treatstock API documentation](https://www.treatstock.com/help/article/83-api-documentation)

### Inferences
- **Fit with PartCAD's missing token write-back:**
  - **OnSite** and **Shapeways (per-user app, `client_credentials`)** fit today: the stored parameters are long-lived client credentials, and the plugin mints a short-lived token on each call.
  - **Slant** and **3DAPI** keys fit trivially, since they are static.
  - **Shapeways' multi-user authorization-code flow** and **3DAPI's OAuth** both depend on refresh-token rotation. They need the write-back mechanism PartCAD lacks, or the user must re-run `pc login` whenever the refresh token is lost or rotated.
- PartCAD can follow least privilege only with 3DAPI: it could recommend a `quotes:read quotes:write orders:read` key for users who only want quotes, and add `orders:write` only for ordering. No other candidate lets a stolen key be prevented from spending money.

### Gaps
- OnSite's access-token lifetime and any rate limit are unpublished, and could not be measured without credentials.
- Whether Slant's "regenerate" keeps the key ID and invalidates the old secret immediately was not tested.
- 3DAPI's OAuth access-token lifetime and refresh-token rotation policy are not published in the docs I read.

## Q3. Can an anonymous, no-credential client quote, or order?

### Takeaway
Yes on two services. **Craftcloud** quotes and orders with no credential; the order is tied only to the email and addresses sent with it. **Slant 3D's** public MCP server quotes and produces a checkout link with no key. **3DAPI** serves its materials catalogue and shipping rates publicly but requires a key to quote. **OnSite**, **Slant's REST API** and **Shapeways** require credentials for everything except, at Shapeways, the discovery documents.

### Cited Findings
- **Craftcloud:**
  - `GET /v5/health_check` answers `{"status":"ok"}`.
  - `GET /v5/price/<unknown id>` answers JSON 404 `{"status":404,"message":"Price not found"}` rather than 401.
  - `GET customer-api.craftcloud3d.com/model/<unknown id>` answers JSON 404 `{"error":"Model not found"}`.
  - No response carried a rate-limit or auth-challenge header.

  Probed — [Craftcloud health](https://api.craftcloud3d.com/v5/health_check); [Craftcloud customer API](https://customer-api.craftcloud3d.com/model/00000000-0000-0000-0000-000000000000)
- **Craftcloud upload** uses a different host from the spec: `POST customer-api.craftcloud3d.com/model/upload/initiate {fileName, fileUnit}` → presigned S3 `PUT` → `POST …/model/upload/confirm {uploadId}` → poll `GET …/model/{modelId}` until `isParsing:false`. Then `POST api.craftcloud3d.com/v5/price` → `GET /v5/price/{id}` until `allComplete` → `POST /v5/cart`. A third-party author reports this "verified live on 2026-10-13, no account or key required" (secondhand; I could not run the POSTs) — [three.ws craftcloud adapter](https://github.com/nirholas/three.ws/blob/HEAD/api/_lib/print/adapters/craftcloud.js)
- The downloaded spec lists no `/v5/model` path at all. The `POST /v5/model` multipart endpoint in the shapeMint transcription is therefore either an older or alternative route, or a mis-transcription. Probed — [Craftcloud spec](https://api.craftcloud3d.com/api-docs.json); [shapeMint notes](https://github.com/MattSharp05/shapeMint/blob/HEAD/docs/API_information/craftcloud_api_merged.md)
- **Craftcloud orders are guest orders:** `POST /v5/order` requires `user{emailAddress, shipping, billing}` and carries an `appId` enum (`craftcloud`, `hp`, `teleport`). Probed — [Craftcloud spec](https://api.craftcloud3d.com/api-docs.json)
- **Paying for a Craftcloud order:** one integrator sends buyers to `https://craftcloud3d.com/order/{order_id}/checkout` to pay, and to `…/order-status/{order_id}` to follow the order. It states that an unpaid order expires after 90 days and that "nothing is made until you pay on Craftcloud's checkout" (secondhand) — [Kiln provider_terms.py](https://github.com/codeofaxel/Kiln/blob/HEAD/kiln/src/kiln/provider_terms.py)
- **Slant MCP:** the public MCP server needs "no API key", and an agent "can upload an STL, get pricing, rate shipping and create a checkout link" — [Slant 3D llms.txt](https://www.slant3d.com/llms.txt); [Slant 3D FAQ](https://www.slant3d.com/faq). Its own page says: "No survey questions, no account setup — upload a model, pick a quantity, choose shipping, pay" — [Slant MCP server page](https://www.slant3d.com/mcp-server)
- **3DAPI public endpoints:** `GET /v2/health`, `/v2/shipping/rates`, `/v2/shipping/quote`, `/v2/materials` and `/v2/categories`, plus integrator sign-up. Quoting needs `quotes:write` — [3DAPI authentication guide](https://public-api.dapi.digital/docs/guides/authentication.md)
- 3DAPI probes:
  - `/v2/health` answered `{"status":"ok","database":"up",…}`.
  - `/v2/materials` returned 23 materials, all `fdm`, `pla` or `petg`.
  - `/v2/shipping/rates` returned a USD rate card by zone (US small parcel $7.49, medium $9.99, large $14.99) and weight tier (small ≤600 g, medium ≤2 kg).

  Probed — [3DAPI materials](https://public-api.dapi.digital/v2/materials); [3DAPI shipping rates](https://public-api.dapi.digital/v2/shipping/rates)
- **Shapeways:** `api.shapeways.com/` and `/materials/v1` answer without auth, but with discovery documents (revision "20121123"/"20130228"), not data. Probed — [api.shapeways.com](https://api.shapeways.com/)

### Inferences
- A Craftcloud plugin can run `caps` and `quote` with no `pc login` at all. For `order`, it creates the order with the user's email and addresses and returns the checkout URL. The user's "own credentials" then amount to their email address and the hosted checkout. PartCAD should say so plainly.
- Slant's public MCP server is a credential-free fallback for quoting, and for ordering through a hosted payment link. It is MCP over Streamable HTTP, though, not the REST API.

### Gaps
- I could not confirm directly that Craftcloud's upload-initiate rejects or accepts a given extension (the POST was blocked).
- Whether a Craftcloud order can be listed later from a Craftcloud account created with the same email is described only as "let us know the order numbers" — [Craftcloud: benefits of an account](https://support.craftcloud3d.com/en/articles/211-what-are-the-benefits-of-creating-a-craftcloud-account)

## Q4. Craftcloud's open questions: upload formats, material catalogue, terms for third-party clients, rate limits

### Takeaway
**Craftcloud accepts STEP**, along with 3MF, OBJ and twelve other formats, for 3D printing, and requires STEP or IGES for CNC (help article dated 2026-10-27). **Its live material catalogue is a public, unauthenticated JSON** at `customer-api.craftcloud3d.com/material-catalog`, cacheable for 12 hours. The 2020 `@all3dp/material-structure` npm package is a stale subset whose IDs largely remain valid. **No rate limit and no explicit third-party-client terms were found.** The site's terms page is blocked to fetchers.

### Cited Findings
- **Formats:** "Craftcloud supports 16 file formats for manufacturing… 3D Printing Supported Formats: 3dxml, .3mf, .brep, .dae, .glb, .gltf, .iges, .igs, .obj, .off, .ply, .step, .stl, .stp, .xaml, and .zip archives." CNC, moulding and casting, and sheet metal accept only ".step, .stp, .iges, .igs, .brep, and .zip". "Standard single-color prints usually work best with .stl or .step files." For colour, use .3mf, or .obj plus .mtl. JSON-LD `dateModified: 2026-10-27`. Probed — [Craftcloud: Which file formats does Craftcloud support](https://support.craftcloud3d.com/en/articles/189-which-file-formats-does-craftcloud-support-for-3d-printing-cnc-machining-sheet-metal-fabrication-and-molding-and-how-do-i-convert-them)
- **File size:** "The maximum individual file size for 3D model uploads on Craftcloud is 500 MB" (modified 2026-06-17). Probed — [Craftcloud: maximum file size](https://support.craftcloud3d.com/en/articles/18-what-is-the-maximum-file-size-i-can-upload-to-craftcloud)
- **Units:** the spec's `fileUnit` enum is `["mm","cm","in"]`. Probed — [Craftcloud spec](https://api.craftcloud3d.com/api-docs.json)
- **Live catalogue:**
  - `GET https://customer-api.craftcloud3d.com/material-catalog?locale=en` answered 200 JSON (3.5 MB) with no credentials. It answered the same with no User-Agent, a generic one or a custom one, and with no `Origin`.
  - Headers: `cache-control: public, max-age=43200`.
  - Shape: `{materialStructure:[group{id,name,materials:[material{id,name,technology,printingMethods[],maximumPrintingDimensions,availableProviders[],apps[],tensile/flexural/HDT data,…,finishGroups:[{id,name,materialConfigs:[{id,name,color,colorCode,colorId,…}]}]}]}]}`.

  Probed — [Craftcloud material catalogue](https://customer-api.craftcloud3d.com/material-catalog?locale=en)
- **Catalogue contents on 2026-11-22:**
  - 15 groups (Nylons, Standard Plastics, Steels, Prototyping Resins, Alloys, Composites, Functional Resins, Engineering Plastics, Flexible Plastics, Precious Metals, Recycled Plastics, Pure Metals, Ceramics, Others, Multicolor).
  - 377 materials and 3,874 `materialConfigId`s: 3,620 `3d_printing` and 254 `cnc_machining`.
  - By printing method: FDM 1,483, MJF 905, SLS 729, SLA 364, DLP 352, LCD 349, MSLA 333, PolyJet 293, CNC 229, SLM/DMLS 55, and others.
  - 177 distinct provider IDs in `availableProviders`. `apps` include `craftcloud` and `hp`.

  Probed, counted locally — [Craftcloud material catalogue](https://customer-api.craftcloud3d.com/material-catalog?locale=en)
- **Sanctioned URL:** Kiln's log says the HTTPS catalogue URL was changed "per Craftcloud's request" (secondhand) — [Kiln COMPLETED_TASKS.md (mirror)](https://github.com/LeoYeAI/agent-master-skills/blob/HEAD/skills/kiln/COMPLETED_TASKS.md)
- **npm package:**
  - `@all3dp/material-structure` latest is **2.32.0, published 2020-03-19** (MIT, All3dp GmbH). It holds 3 groups, 39 materials and 286 `materialConfigs`. Its README says "The files in `export` should be imported by the server".
  - **262 of its 286 IDs are still present** in the live catalogue.
  - All three `materialConfigId`s that appear in the live spec's examples exist in the 2020 package: PLA Gray (FDM), Polished Dyed Purple SLS Nylon, and 14k Gold lost-wax casting.

  Probed and compared locally — [npm @all3dp/material-structure](https://www.npmjs.com/package/@all3dp/material-structure); [Craftcloud spec](https://api.craftcloud3d.com/api-docs.json)
- **Rate limits:** "Craftcloud didn't specify a rate limit" (Kiln, after its partner email; secondhand) — [Kiln COMPLETED_TASKS.md (mirror)](https://github.com/LeoYeAI/agent-master-skills/blob/HEAD/skills/kiln/COMPLETED_TASKS.md). The spec contains no rate-limit language, and none of my responses carried rate-limit headers. Probed — [Craftcloud spec](https://api.craftcloud3d.com/api-docs.json)
- **Webhooks and polling:** there are no webhooks; Craftcloud recommends polling order status and pricing over WebSocket (secondhand, same log) — [Kiln COMPLETED_TASKS.md (mirror)](https://github.com/LeoYeAI/agent-master-skills/blob/HEAD/skills/kiln/COMPLETED_TASKS.md)
- **Terms:**
  - `craftcloud3d.com/en/p/terms-and-conditions` answered 403 to both the fetch tool and curl. Cloudflare blocks the main site (`craftcloud3d.com/`, `/en/upload`) to non-browser clients, though `robots.txt` reads `Allow: /`. Probed — [Craftcloud terms](https://craftcloud3d.com/en/p/terms-and-conditions); [Craftcloud robots.txt](https://craftcloud3d.com/robots.txt)
  - Kiln summarises those terms for buyers (secondhand): the order "becomes binding when you confirm the purchase" at checkout; a change after ordering is "refunded minus a handling fee of up to 7%"; customs and duties are the buyer's — [Kiln provider_terms.py](https://github.com/codeofaxel/Kiln/blob/HEAD/kiln/src/kiln/provider_terms.py)
  - Kiln reports that Craftcloud "said payment handling depends on the integration type" (secondhand) — [Kiln COMPLETED_TASKS.md (mirror)](https://github.com/LeoYeAI/agent-master-skills/blob/HEAD/skills/kiln/COMPLETED_TASKS.md)

### Inferences
- PartCAD can send **STEP** to Craftcloud. Help text and the account page ("STL, STEP, OBJ, etc.") both say so. That removes the "STL in every example" blocker from the earlier report, although an upload through the API path has not been exercised.
- `caps` can now come from a live, public source: fetch the catalogue, cache it for its 12-hour `max-age`, and map `materialConfigId`s through `material → finishGroup → materialConfig` to PartCAD materials, colours (`colorCode` is a hex value) and finishes. The npm package is fine as a frozen fallback, but it misses roughly 92% of today's configurations.
- The 403 on the website is bot protection on the marketing site, not on the API hosts. A plugin talking to `api.` and `customer-api.` is unaffected.

### Gaps
- No explicit permission or prohibition for third-party API clients was found; the terms page could not be read.
- No published rate limit. Kiln's 2-second poll interval is the only practical reference (secondhand).

## Q5. Slant 3D's open questions: self-serve signup, terms and pricing, international shipping, test doubles

### Takeaway
Key signup is **self-serve** (email and password, or Google) with no approval step. Ordering additionally needs a Stripe card on the account and a "platform" record. The published Terms of Service (effective 1 January 2023) say nothing about the API, automation or third-party clients. There is no API fee: you pay for parts. **International shipping is advertised but unproven in the schema** (`country` defaults to `US`). **The community mock server mirrors the dead v1 API, not v2.**

### Cited Findings
- Sign-up and key generation are self-serve, and there is no approval or waitlist wording in the dashboard bundle. The only gates are email verification and a disposable-email check. Probed — [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js)
- Terms of Service: "Effective Date: January 1, 2023 Jurisdiction: State of Idaho". "Payments are due in full prior to the start of production". "All fees are non-refundable once production has commenced". A marketing-use clause applies ("permission to reference your company name and logo… If you wish to opt out, you must explicitly notify us in writing"). There is no clause on APIs, bots or third-party apps. Probed — [Slant 3D Terms of Service](https://www.slant3d.com/slant-3d-user-agreement)
- Pricing: the API page says "No tooling cost". Portals "is completely free — no subscriptions, no listing fees". "Same API that powers Portals and Teleport. Get a key and start shipping plastic from a curl command." No API subscription price was found. The dashboard code has `free/standard/premium/admin` role tiers, whose meaning is undocumented. Probed — [Slant 3D API overview](https://www.slant3d.com/api); [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js)
- International shipping:
  - API page: "Create customers, place orders, and let us handle fulfillment, warehouse tracking, and international shipping".
  - Portals "ships worldwide".
  - FAQ: Slant "prints and ships from the United States".
  - Docs field note: `state` "Can be included for US orders / International region".
  - Spec: `Address.country` has `"default": "US"`, and every price field is USD.

  Probed — [Slant 3D API overview](https://www.slant3d.com/api); [Slant 3D FAQ](https://www.slant3d.com/faq); [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js); [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json)
- Health: `GET /v2/api/health/status` (public) answered `success:true`, with PAYMENT-SERVICE, ORDER-SERVICE, FILES-SERVICE, KRAKEN and TELEPORT all `healthy`. Probed — [Slant health](https://slant3dapi.com/v2/api/health/status)
- **v1 is gone:** `slant3dapi.com/api/filament`, `www.slant3dapi.com/api/filament` and `/api/order` all answer `502 Bad Gateway` (nginx). Probed — [Slant v1 filament](https://slant3dapi.com/api/filament)
- **The mock server mirrors v1:** `justinluttrell/mock-slant-pod` implements `/api/filament`, `/api/slicer`, `/api/order/estimate`, `/api/order/estimateShipping`, `/api/order` and `/api/customer/subscribeWebhook`. These are the **v1** paths, not v2's `/v2/api/files/direct-upload`, `/orders`, `/orders/{publicId}` — [mock-slant-pod README](https://github.com/justinluttrell/mock-slant-pod/blob/HEAD/README.md)
- **Draft-order prerequisites:** "Drafting an order will not charge your account… you do need a connected payment method on your account… Customer details are necessary for estimating shipping costs… Orders can only be drafted once a valid platform exists". Refunds: "Not Integrated yet. Use Cancel Order". Probed — [slant3dapi.com bundle](https://slant3dapi.com/assets/index-C5Wnw4hq.js)

### Inferences
- The earlier report's claim that Slant has a "public mock server [that] simulates the whole order flow… so CI never has to spend money" no longer holds for v2. A PartCAD test double for Slant v2 would have to be written from the OpenAPI spec, for example with a spec-driven mock such as Prism. That last step is an inference, not a verified tool test.
- A non-US Slant quote can only be settled empirically: draft an order with a non-US address and read `deliveryCost`. Drafting does not charge.

### Gaps
- Whether `POST /orders` returns a `deliveryCost` for a non-US address was not tested (it needs a key and a card on file).
- I found no Slant API-specific terms, SLA or published per-order fee.

## Q6. 3DAPI's open questions: actual endpoint paths and the approval process

### Takeaway
The integrator surface is confirmed from the OpenAPI 3.1 spec (1.6 MB, `3DAPI API 2.0.0`, server `https://public-api.dapi.digital`). The flow is: upload slot → PUT → `POST /v2/quotes` → poll `GET /v2/quotes/{id}` → `POST /v2/integrator/orders/shipping-estimate` → `POST /v2/integrator/orders` in `wallet` or `checkout` mode. Approval is a human review of 10 quoted files, taking 24–48 h. There is no sandbox.

### Cited Findings
- Integrator operations, by path, operation ID and accepted scopes:
  - `POST /v2/uploads` (`create_upload`; purpose `quote_file`)
  - `POST /v2/quotes` (`create_quote`, `quotes:write`)
  - `GET /v2/quotes`, `GET /v2/quotes/{id}` (`quotes:read`)
  - `POST /v2/integrator/orders/shipping-estimate` (`orders:read`)
  - `POST /v2/integrator/orders` (`create_integrator_order`, `orders:write`)
  - `GET /v2/integrator/orders[/{id}]` (`orders:read`)
  - `POST /v2/integrator/orders/{id}/cancel` (`orders:write`)
  - `GET /v2/integrator/onboarding`, `POST /v2/integrator/approval-requests`
  - `GET /v2/wallet`, `/v2/transactions` (`wallet:read`)
  - `GET /v2/me`

  Session-only operations include API keys, cards, top-ups, billing details and webhook-endpoint writes. Probed — [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)
- `POST /v2/quotes` "returns the quote with `status: processing`. Poll `get_quote` until it is `ready` (with `price`) or `failed`". The price is for 3DAPI's production version of the file. "Limits before your account is approved: up to 25 quotes per round, and none while an approval request is in review". Probed — [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)
- `POST /v2/integrator/orders`:
  - Requires `mode` (`wallet`|`checkout`), `items[{quote, quantity}]` (1–100 lines), `shipping_address{…, country_code}` and `customer{name, email, phone}`.
  - **Wallet mode** returns a paid order numbered `2AP…`.
  - **Checkout mode** returns `awaiting_payment` with `checkout.url`, valid for 24 h.
  - `checkout.success_url`/`cancel_url` "Must be https; plain http is accepted only for localhost and 127.0.0.1".
  - All money is in lower-case `usd` minor units.

  Probed — [3DAPI OpenAPI](https://public-api.dapi.digital/docs/openapi.json)
- Quote files are `.stl`, `.3mf`, `.obj`, `.step` and `.stp`, up to 250 MiB. Upload IDs expire after 24 h — [3DAPI FAQ](https://public-api.dapi.digital/docs/guides/faq.md)
- Approval:
  - "Your integrator account is approved once 10 files are approved… People review the request file by file, which usually takes 24 to 48 hours… you get an email when it is done". Approved files stay approved across rounds — [3DAPI: submit sample files](https://public-api.dapi.digital/docs/guides/request-integrator-approval.md)
  - "Order to Quote ratio 1:1500" — [3DAPI quickstart](https://public-api.dapi.digital/docs/guides/quickstart.md)
  - Daily quote caps reset at midnight UTC before approval — [3DAPI FAQ](https://public-api.dapi.digital/docs/guides/faq.md)
- Shipping worldwide except Russia, Belarus, Iran and Syria. EU and UK businesses pay VAT on wallet top-ups unless VIES confirms their VAT number — [3DAPI FAQ](https://public-api.dapi.digital/docs/guides/faq.md)

### Inferences
- PartCAD's `quote` maps to: upload the STEP, create the quote, poll until it is ready, run the shipping estimate, then `price × qty + shipping`. The cart ID is synthesised client-side, because 3DAPI has no server cart. Quote IDs (`qte_…`) can be carried in it.
- PartCAD's `order` maps to wallet mode (no browser step) or checkout mode. Checkout mode returns a URL and can bring the user back to a loopback `success_url`.
- The 10-file human review, plus a 25-quote cap per round before approval, makes 3DAPI awkward for a casual first-time PartCAD user.

### Gaps
- The legal domicile of "3DAPI Inc." and the company's financial health remain unknown.
- Whether the "Order to Quote ratio 1:1500" is enforced, and how, is not explained.

## Q7. Shapeways: is v1 supported after the relaunch, does upload take STEP, is app registration open?

### Takeaway
The relaunched company **markets the API as a current product** on a 2026 page ("API access is completely free, and each customer order carries a flat 5% transaction fee"). The OAuth authorize endpoint and the app-management page are live behind the new login. The API reference itself is unchanged since 2012–2013. Upload takes any file "with correct file extension". STEP is listed by the support centre, but STEP through the API path is not stated and was not tested.

### Cited Findings
- The e-commerce integrations page (footer "© 2008 - 2026 Shapeways", ISO 9001/14001 claims) has a "Shapeways API" section: "Connect your custom website to Shapeways with our free API. API access is completely free, and each customer order carries a flat 5% transaction fee." Volume discounts are by email. Probed — [Shapeways e-commerce integrations](https://www.shapeways.com/business/e-commerce-integrations)
- The API Terms & Conditions are "Last updated: August 9, 2018". Their main terms:
  - "a 5 percent transaction fee for all orders placed through the Shapeways API… charged to the credit card associated with the Developer"
  - the Developer must "provide all customer support to its customers" and "limit orders only to shipping locations which are in an approved Shapeways shipping country"
  - no "robot, spider, scraper or other automated means other than the API"
  - "we do implement standard rate limiting"
  - a licence "to use the API for Developer's internal use, including… making the functionality… available to Developer's end users"

  Probed — [Shapeways API Terms & Conditions](https://developers.shapeways.com/terms-and-conditions)
- `POST /models/v1` takes `fileName` "Model filename (with correct file extension)". `uploadScale` is "required for .stl / .obj / .vox, otherwise optional". No extension list is given in the API reference. Probed — [Shapeways API reference](https://developers.shapeways.com/api-reference)
- Live state of the endpoints:
  - The discovery document still reports revision "20121123".
  - The `/oauth2/authorize` endpoint redirects to the sign-in page.
  - `developers.shapeways.com/manage-apps` redirects to `portal.shapeways.com/login`.

  Probed — [api.shapeways.com](https://api.shapeways.com/); [Shapeways manage apps](https://developers.shapeways.com/manage-apps)

### Inferences
- The 2026 marketing page and the live OAuth and app-management endpoints are good evidence that API orders are at least intended to work post-relaunch. Only a real order (or Shapeways' reply to api@shapeways.com) would prove it.
- The 2018 terms cast the integrator as a "Developer" who resells to "Customers", pays the 5% fee and handles support. If each PartCAD user registers their own app, each user is their own "Developer" and the fee lands on their own card. That is consistent with the terms, but the fee should be surfaced in `quote`.

### Gaps
- No primary statement after the relaunch on API maintenance, rate limits or deprecation.
- STEP through `POST /models/v1` was not tested (it needs an account and a token).

## Q8. Materialise OnSite: who can get access, does it ship to the US, which formats?

### Takeaway
Any active OnSite account can ask for API enablement by email; the help page does not restrict it to businesses. Ordering through the API also needs invoice payment enabled (established earlier). **OnSite ships to the USA** from Leuven by UPS Express Saver, at €24 for parcels up to 3 kg, with US duties unpaid. Formats are as in the earlier notes, STEP included. Auth is strictly `client_credentials`.

### Cited Findings
- Shipping table: UPS Express Saver costs EU €17, **USA €24**, Rest of World €35 (≤3 kg); €34/€82/€95 (≤15 kg); €82/€355/€210 (>15 kg). "UPS Standard is not available for non-EU destinations, excl. UK, Switzerland and Norway". "For all other countries, there will be duties or import taxes but they are not included in the shipping cost." Probed — [OnSite help: General shipment information](https://onsite.helpjuice.com/en_US/general-shipment-information-2)
- Most products ship from Leuven, Belgium (search summary) — [OnSite help: Where do you ship from?](https://onsite.helpjuice.com/en_US/where-do-you-ship-from)
- API access requires "an active OnSite account with API integration enabled". Request it by email ("subject API"). There is no sandbox, no stated rate limit, and the footer reads "© Copyright Materialise 2022" — [OnSite help: Summary API documentation](https://onsite.helpjuice.com/api-connection/summary-api-documentation)
- The spec contains no file-extension enum. Upload errors say "The file extension is not supported" (established earlier). Probed — [OnSite swagger.json](https://api.onsite.materialise.com/documentation/v1/swagger.json)

### Inferences
- OnSite is viable for US PartCAD users who have invoice terms, at roughly €24 or more in transport per order plus import duties. It remains a business-buyer option.

### Gaps
- Whether invoice payment, and with it API ordering, is granted to non-company accounts, or to US accounts at all, is not stated.

## Q9. Sandbox, test mode or mock server for developing without real orders

### Takeaway
No candidate offers a real sandbox in November 2026. Craftcloud has an `isTestOrder` flag on payment requests. 3DAPI says plainly that there is "no sandbox or test mode", but gives a $15 sample credit after approval. Slant's only mock server mirrors the retired v1 API. OnSite, Shapeways and Treatstock document nothing.

### Cited Findings
- Craftcloud's payment requests (`stripe`, `paypal`, `adyen`, `invoice`, `quote`) take `isTestOrder: boolean, default false`. Its effect on Stripe (test mode or not) is not described. Probed — [Craftcloud spec](https://api.craftcloud3d.com/api-docs.json)
- 3DAPI: "Is there a sandbox or test mode? No. Every request works on your real account". The $15 sample credit is valid 30 days, for wallet orders shipped to your own country — [3DAPI FAQ](https://public-api.dapi.digital/docs/guides/faq.md)
- The Slant 3D spec contains none of the words "sandbox", "test mode" or "mock". Probed — [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json). The community mock implements v1 paths only — [mock-slant-pod README](https://github.com/justinluttrell/mock-slant-pod/blob/HEAD/README.md)
- Slant has `POST /platforms/{platformId}/webhook/dummy` ("Send test webhook"). That tests webhooks, not orders. Probed — [Slant OpenAPI](https://slant3dapi.com/v2/api/openapi.json)

### Inferences
- PartCAD's CI for these plugins should rely on recorded responses or spec-generated mocks. Each service publishes a machine-readable spec (Craftcloud Swagger 2.0, Slant OpenAPI 3.0.3, 3DAPI OpenAPI 3.1, OnSite Swagger 2.0). The only free live calls are Craftcloud's quote path and the public catalogue and shipping endpoints of 3DAPI and Craftcloud.

### Gaps
- Whether Craftcloud's `isTestOrder: true` produces a Stripe test-mode checkout that a developer can complete with a test card was not tested.

## Q10. Treatstock and JLC3DP, briefly

### Takeaway
Neither fits per-user credentials. Treatstock's tokens come from a contact form, and the full-access token must not be exposed to users. JLC3DP's signed app credentials come from an approval process that weighs order history.

### Cited Findings
- Treatstock: "Get API tokens" leads to a contact form. Formats are STL, PLY and 3MF. Limits are per key. Probed — [Treatstock API documentation](https://www.treatstock.com/help/article/83-api-documentation)
- JLCPCB/JLC3DP: application at api.jlcpcb.com, no code reviews by support. The HMAC-signed `JOP` authorization header is reported by third-party clients (secondhand) — [JLCPCB API access article](https://jlcpcb.com/help/article/jlcpcb-online-api-available-now); [Pipedream JLCPCB (search summary)](https://pipedream.com/apps/jlcpcb/integrations/amazon-ses)

### Inferences
- A per-user JLC3DP plugin is conceivable, since each user applies for their own app ID and secret and pastes them with `--set`. Approval depends on each user's JLCPCB order history, though, so most PartCAD users would be refused.

### Gaps
- Whether JLC3DP's 3D-printing API uses the same signing scheme as its PCB API, and which formats it accepts, are behind the application.
