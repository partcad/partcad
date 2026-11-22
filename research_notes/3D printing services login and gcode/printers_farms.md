# Sending a sliced print job to a printer or print farm: APIs, file formats and status, as of November 2026

Scope: the route from a CAD-as-code tool's own G-code (or a sliced 3MF) to a printer or farm, and status back. This
extends `docs/design/additive.md` §7.4 (3MF Slice/Toolpath) and §12.4 (slicers and licences). It does not cover print
services that re-slice a mesh; another researcher covers those. "Unverified" marks anything taken from a search snippet,
a competitor's page, or a single forum post rather than a primary source. No accounts were created, so nothing behind a
login was read.

## 1. Printer and host APIs: upload, start, file types, auth, remote access, status, terms

### Takeaway
Three open hosts take your own G-code and start it with one documented HTTP call: OctoPrint (`print=true`), Moonraker
(`print=true`) and PrusaLink (`Print-After-Upload: ?1`). All three are LAN APIs. PrusaLink and OctoPrint are AGPL and
Moonraker is GPL-3.0, but a client speaking HTTP to them is not bound by those licences. Bambu is the exception. Since
January 2025 its firmware refuses third-party print starts unless the client goes through Bambu's closed Bambu Connect
app, the printer is put in unsupported Developer Mode, or (since mid-2026) a Bambu Fleet Hub appliance with
developer-certificate activation is used. Its cloud is off-limits by contract, and Bambu enforced that with a takedown
in April 2026. Formlabs, UltiMaker Digital Factory and Markforged Eiger have real APIs. Formlabs takes meshes and
`.form`, UltiMaker takes G-code or UFP, and Markforged slices in its own cloud. None of the three runs a route that
PartCAD wrote itself, except UltiMaker's G-code.

### Cited Findings

**OctoPrint (open source, LAN; remote only through a tunnel or plugin)**
- OctoPrint **2.0.0 was published to PyPI on 2026-11-16** and 2.0.1 on 2026-11-18. It is licensed AGPL-3.0-or-later — [PyPI OctoPrint JSON](https://pypi.org/pypi/OctoPrint/json). (Web search found only the release candidates, rc1 in April 2026 through rc5 in August 2026 — [OctoPrint blog rc5](https://octoprint.org/blog/2026/08/24/new-release-candidate-2.0.0rc5/).)
- Upload is `POST /api/files/{location}` as `multipart/form-data`. The form fields are `file`, `select`, `print` ("Starts printing after upload. Implies `select`"), `path` and `userdata`. The locations are `local` and `printer`, and `sdcard` is now a "deprecated alias for `printer`". The call answers **415 "If the file is neither a `gcode` nor an `stl` file"**, and 409 if the printer is busy. The documented examples authenticate with `Authorization: Bearer ...` and send `X-OctoPrint-Api-Version: 2.0.0` — [OctoPrint docs, File operations (master)](https://docs.octoprint.org/en/master/api/files.html).
- OctoPrint 2.0 adds API versioning through the `X-OctoPrint-Api-Version` header. A request without the header keeps the pre-2.0 behaviour. 2.0 also requires Python 3.9 or later, replaces `trustedRemoteUser` with a list of trusted authentication proxies, and lets plugins provide printer interfaces other than serial — [OctoPrint 2.0.0 migration / general API docs via search](https://docs.octoprint.org/en/dev/plugins/migration_2_0_0.html); [API general](https://docs.octoprint.org/en/dev/api/general.html).
- The rc3 post says OctoPrint up to 1.11.7, and 2.0.0rc1/rc2, are affected by security vulnerabilities — [OctoPrint blog rc3](https://octoprint.org/blog/2026/06/23/new-release-candidate-2.0.0rc3/) (via search snippet).

**Moonraker (Klipper's API server; GPL-3.0; LAN)**
- Moonraker is licensed GPL-3.0 — [Moonraker LICENSE](https://raw.githubusercontent.com/Arksine/moonraker/master/LICENSE).
- Upload is `POST /server/files/upload` (`multipart/form-data`, the file in the `file` part). `root` "may only be `gcodes` or `config`". `path` names the subfolder. `checksum` is an optional SHA256, and a mismatch answers 422. **`print=true` has Moonraker "command Klippy to start the print after the upload has successfully completed"**, and the response reports `print_started` / `print_queued` — [Moonraker docs, file manager](https://moonraker.readthedocs.io/en/latest/external_api/file_manager/).
- `GET /server/files/metadata?filename=` returns `slicer` and `slicer_version`. The fields available depend on what can be parsed from the slicer's output. The gcodes root lists only files with "valid gcode file extensions", but the page does not name them — [same](https://moonraker.readthedocs.io/en/latest/external_api/file_manager/).
- Auth is optional. A third-party client needs an API key only "if your install has `[authorization]` configured". Moonraker listens on port 7125 — [Printago, connecting Creality](https://docs.printago.io/docs/connecting-printers/creality).
- Klipper exposes run-time `SET_PRESSURE_ADVANCE [EXTRUDER=] [ADVANCE=] [SMOOTH_TIME=]` and `SET_INPUT_SHAPER [SHAPER_FREQ_X=] [SHAPER_FREQ_Y=] ...`. The latter is enabled only when `printer.cfg` has an `[input_shaper]` section. `EXCLUDE_OBJECT` takes its object definitions from the G-code file — [Klipper G-Codes](https://www.klipper3d.org/G-Codes.html).
- Several vendors now ship Klipper/Moonraker on their own printers:
  - **Creality K2 series**: Moonraker on 7125 — [Printago Creality](https://docs.printago.io/docs/connecting-printers/creality). SimplyPrint's guide says a K2 needs "root access" — [SimplyPrint K2 Plus](https://simplyprint.io/setup-guide/creality/k2-plus.md). Creality's own route is CrealityPrint 5 LAN control and file transfer — [Creality K2 Plus support](https://www.creality.com/uk/support/creality-k2-plus-cfs-combo) (via search snippet).
  - **Snapmaker U1**: Snapmaker published its modified Klipper, Moonraker and Fluidd forks on GitHub under GPLv3, and some features are in separately developed modules — [Snapmaker blog](https://www.snapmaker.com/blog/snapmaker-u1-firmware-now-on-github). Users hit `401 Unauthorized` from Snapmaker Orca until trusted networks were configured — [Snapmaker forum](https://forum.snapmaker.com/t/resolved-snapmaker-orca-and-u1-issue-error-401-unauthorized-see-solution/41047). One source puts the U1's Moonraker on port 80 rather than 7125, so the port is *unverified* — [ClawHub skill](https://clawhub.ai/snapmaker) vs [Printago Snapmaker](https://docs.printago.io/docs/connecting-printers/snapmaker).

**PrusaLink (on the printer; LAN) and Prusa Connect (cloud)**
- The PrusaLink OpenAPI spec is "PrusaLink Web" **1.0.0-draft, License AGPLv3**. It defines only `digestAuth` as a security scheme. Endpoints:
  - Upload: **`PUT /api/v1/files/{storage}/{path}`**, raw `application/octet-stream`, with headers **`Print-After-Upload: ?1`** and `Overwrite: ?1` (RFC 8941 booleans).
  - Start a stored file: `POST /api/v1/files/{storage}/{path}`.
  - Status: `GET /api/v1/status` (job, printer state, transfer, storage, camera) and `GET /api/v1/job`.
  - Job control: `DELETE`, and `PUT .../pause|resume`, on `/api/v1/job/{id}`.

  Print metadata is "parsed from G-code or SL1" — [Prusa-Link-Web openapi.yaml](https://raw.githubusercontent.com/prusa3d/Prusa-Link-Web/master/spec/openapi.yaml).
- `.bgcode` uploads through the API work, and the web dialog accepts them by drag and drop — [Prusa forum](https://forum.prusa3d.com/forum/hardware-firmware-and-software-help/prusa-link-dashboard-doesnt-recognize-bgcode-files-in-upload-dialog). One MK4 user reports that upload-and-print sometimes waits for a confirmation on the printer instead of starting (anecdotal) — [Prusa forum](https://forum.prusa3d.com/forum/english-forum-original-prusa-i3-mk4-hardware-firmware-and-software-help/disable-needing-to-physically-click-print-on-the-printer-after-network-upload-print).
- Prusa Connect's only **publicly documented** third-party API is the camera API — [Prusa help, Connect Camera API](https://help.prusa3d.com/article/prusa-connect-camera-api_569012). A 2024 forum post says the other endpoints are proprietary — [Prusa forum](https://forum.prusa3d.com/forum/introcuctions-instrutctions/prusa-connect-is-there-api-specification-or-mobile-android-app-with-notifications).
- `https://connect-mobile-api.prusa3d.com/api/docs` serves an OpenAPI 3.1 document titled "Connect mobile API" ("API gateway for Prusa Connect mobile application", version `0.0.1-dev`), retrieved directly. It authenticates with a `client_jwt_token` in `Authorization` or `server_to_server`, and lists:
  - `GET /api/v1/printers` and `GET /api/v1/printers/{printerUuid}/queue`;
  - `PUT /api/v1/printers/{printerUuid}/command/start/cloud|files|printables`;
  - pause, resume and stop;
  - `GET /api/v1/storage/{teamId}`;
  - `GET /api/v1/jobs` and `GET /api/v1/teams`.

  **It has no file-upload endpoint** — [Connect mobile API](https://connect-mobile-api.prusa3d.com/api/docs).
- `prusa-connect-sdk-printer` is the *printer-side* SDK that a printer uses to talk to Connect, not a client for submitting jobs. PyPI lists its licence as "Freeware" — [PyPI](https://pypi.org/project/prusa-connect-sdk-printer/); [GitHub](https://www.github.com/prusa3d/Prusa-Connect-SDK-Printer).

**Bambu Lab (LAN MQTT + FTPS; Bambu Connect; Developer Mode; Fleet Hub; private cloud)**
- **Authorization Control** was announced on 16 January 2025. It requires a Bambu-issued token for print initiation, motion, fan/hotend, AMS, calibration, remote video and firmware upgrade, **even on the LAN**. Starting a job from the SD card at the printer, and status reporting, still work without a token — [7items, citing Bambu and Hackaday](https://7items.com/3d-printing/bambus-authorization-control-now-has-a-legal-test-case/).
- Bambu's own post of 20 January 2025 says:
  - "LAN mode through Bambu Connect will require neither internet access nor a user account".
  - An optional **Developer Mode** on X1, P1, A1 and A1 mini "leave[s] the MQTT channel, live stream, and FTP open". It must be enabled manually, and Bambu provides no customer support for it.
  - Bambu built "a dedicated tool specifically designed for farm management software" and invites developers to devpartner@bambulab.com.

  — [Bambu blog, Updates and Third-Party Integration with Bambu Connect](https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/).
- **Bambu Connect URL scheme**: `bambu-connect://import-file?path=<absolute path, encodeURIComponent>&name=<name>&version=1.0.0`. The Chinese wiki says it "securely sends already-sliced Bambu Lab gcode 3MF files to the printer and prints them" — [Bambu wiki, Bambu Connect (via search snippet; the wiki answered HTTP 402 to a direct fetch)](https://wiki.bambulab.com/en/software/bambu-connect); [zh](https://wiki.bambulab.com/zh/software/bambu-connect). Through it, a slicer can send a file and request a print, but cannot control temperature, motion or the AMS — [7items](https://7items.com/3d-printing/bambus-authorization-control-now-has-a-legal-test-case/). An older forum post says Bambu Connect has no Linux version (*unverified for 2026*) — [Bambu forum](https://forum.bambulab.com/t/tool-to-send-files-to-bambu-connect-using-lan-mode/138714).
- Bambu's wiki tells third-party developers to "Apply for SDK Access" for Bambu Connect (*unverified, search snippet only*) — [Bambu wiki, third-party integration](https://wiki.bambulab.com/en/software/third-party-integration).
- **LAN protocol (community-documented)**:
  - MQTT over TLS at `{printer}:8883`, user `bblp`, password = the LAN access code. Topics are `device/{serial}/request` and `device/{serial}/report`.
  - `print.project_file` takes `url` (`file:///mnt/sdcard/...` or an `ftp://` path), `param` (`Metadata/plate_N.gcode`), `md5`, `bed_levelling`, `flow_cali`, `vibration_cali`, `layer_inspect`, `use_ams` and `ams_mapping`. With a wrong `ams_mapping` the printer pauses and will not start.
  - The cloud broker is `us.mqtt.bambulab.com:8883`, user `u_{USER_ID}`.
  - `push_status` reports `gcode_state`, `mc_percent`, `mc_remaining_time`, `layer_num`, temperatures and `hms`.

  — [OpenBambuAPI mqtt.md](https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md).
- **Cloud is closed by contract.** Bambu, 7 May 2026: "Our cloud is a private service. Access to it is governed by a user agreement, not the AGPL license." It also says "impersonating official clients in communication with our cloud infrastructure is not allowed", and points users at "Bambu Connect, LAN Mode and Developer Mode". The post names no public API or SDK — [Bambu blog, 7 May 2026](https://blog.bambulab.com/setting-the-record-straight-on-cloud-access-and-community/).
- On 23 April 2026 a developer published "OrcaSlicer-bambulab", which restored direct network printing. Bambu demanded a takedown and said a cease-and-desist letter was prepared, and the repository was deleted the same day. Bambu's Terms of Use §3.4–3.5 restrict reverse engineering and bypassing rights systems — [7items](https://7items.com/3d-printing/bambus-authorization-control-now-has-a-legal-test-case/); [Tom's Hardware](https://www.tomshardware.com/3d-printing/developer-re-enables-3d-printer-features-that-bambu-lab-disabled-firm-promptly-threatens-legal-action-orcaslicer-bambulab-project-now-shuttered).
- **Bambu Fleet Hub** (a LAN appliance with an official API). The source is the official Technical White Paper v1.01 (v1.0 dated 2026-05-20, last updated 2026-07-09):
  - "up to 50 printers" and "RESTful APIs".
  - An mTLS HTTP server on **TCP/8888** and an mTLS MQTT broker on TCP/1883 for the printers.
  - Activation needs a developer-center **Activation Key** and **client certificates**: up to five, RSA-2048 or stronger, issued after uploading a public key. An activation ticket is forwarded to Bambu's cloud; the hub itself does not reach the cloud.
  - Printers managed this way "operate exclusively on LAN and cannot be accessed via Bambu Handy or cloud services".
  - Print jobs: "the corresponding **gcode.3mf** file must be prepared in advance". It is uploaded to the hub's 40 GB MD5-indexed cache, or fetched by the printers from an HTTPS URL you host. One job can target several printers.
  - Supported printers, with minimum firmware: A1/A1 mini, P1P/P1S, X1C, X1E, H2D, H2D Pro, H2S, P2S, X2D.

  — [Fleet Hub Technical White Paper v1.01 (PDF)](https://portal.bblmw.com/fleet-hub/wb76oog4i8k/files/Fleet%20Hub%20Technical%20White%20Paper%20EN%20v1.01.pdf).
- The Fleet Hub developer agreement reportedly bars customers from reselling or sublicensing the authorized API (*unverified, snippet only*) — [Fleet Hub developer agreement](https://bambulab.com/en/fleet-hub/developer/develop-agreement). One article says Fleet Hub is sold only on Bambu's Japanese site (*unverified*; the page answered 403) — [3Druck](https://3druck.com/en/printers-and-products/bambu-lab-fleet-hub-local-control-box-for-printer-fleets-with-api-and-cloud-free-operation-19165100/).

**Elegoo, Anycubic**
- **Elegoo Centauri Carbon (CC1)** speaks SDCP v3.0.0 over a WebSocket on port 3030 (`ws://{ip}:3030/websocket`), with UDP discovery on port 3000 and an HTTP multipart upload with an MD5 check. Some protocol field names are misspelled — [OpenCentauri API docs](https://suchmememanyskill.github.io/OpenCentauri/software/api). The Centauri Carbon 2 uses MQTT instead. Elegoo reportedly published an Apache-2.0 "Elegoo Link" SDK in January 2026 (*unverified*) — [pycentauri on PyPI (summary)](https://pypi.org/project/pycentauri/).
- **Anycubic** publishes no LAN API. Community clients for the Kobra 3 and S1 use a proprietary MQTT protocol over TLS in LAN mode. One user reports that enabling LAN mode removed the printer from their Anycubic account and could not be undone (a single report) — [kobra-connect](https://github.com/rvanderp3/kobra-connect); [Home Assistant forum](https://community.home-assistant.io/t/anycubic-3d-printer-local-no-cloud-required-dashboard/1014086); [Rinkhals MQTT docs](https://jbatonnet.github.io/Rinkhals/firmware/mqtt).

**Formlabs (resin and SLS; `.form`, not G-code)**
- The Local API is served by **PreFormServer**, a headless app, at `http://localhost:44388` (the port is set with `--port`). Endpoints:
  - `POST /scene/` (`machine_type`, `material_code`, `layer_thickness_mm`) and `POST /scene/import-model/` (a full file path);
  - `POST /scene/auto-orient/`, `/scene/auto-support/`, and `/scene/auto-layout/` (SLA) or `/scene/auto-pack/` (SLS);
  - `POST /scene/save-form/`;
  - **`POST /scene/print/`** (`printer`, `job_name`, `print_now`);
  - `GET /devices/` and `POST /discover-devices/`;
  - `POST /login/`, needed for Fleet Control queues and Dashboard printers.

  Long calls accept `?async=true` — [Formlabs Local API 0.8.9 reference](https://formlabs-dashboard-api-resources.s3.us-east-1.amazonaws.com/formlabs-local-api-v0.8.9.html).
- The latest Local API is **1.0.4 (PreForm 3.65.1), dated 20 November 2026**. The Web API is v0.8.1 (6 December 2024) and covers status, consumables and history for Dashboard-registered printers. Formlabs publishes a Python library on GitHub (`formlabs-api-python`) and a wheel, `formlabs_preform_api`, without stating a licence — [Formlabs API downloads and release notes](https://formlabs.com/support/Formlabs-API-downloads-and-release-notes/); [Formlabs Local API](https://formlabs.com/support/Formlabs-Local-API/).

**UltiMaker Digital Factory, Markforged Eiger**
- In UltiMaker Digital Factory you upload a G-code or UFP to the Cura jobs upload endpoint and get a job ID back, then POST that ID to a cluster's print endpoint and track it with the cluster's `print_jobs`. "Ultimaker doesn't offer cloud slicing for STL files" — [UltiMaker API docs, print job tracking (via search)](https://docs.api.ultimaker.com/guides/print-job-tracking.html); [Connect](https://docs.api.ultimaker.com/connect/index.html). UltiMaker/MakerBot retired CloudPrint in December 2025 and moved users to Digital Factory — [Fabbaloo](https://www.fabbaloo.com/news/ultimaker-retires-cloud-print-and-moves-users-to-new-digital-factory-management-platform); [MakerBot](https://www.makerbot.com/stories/cloudprint-retirement-digital-factory-migration).
- Markforged Eiger API v3: `POST/GET/DELETE https://www.eiger.io/api/v3/devices/{id}/queue`, HTTP Basic with an access key and secret. API access is "included for all customers of Eiger Fleet". An organisation-level "Job Requests" queue also exists — [Eiger developer spec (via search snippet)](https://www.eiger.io/developer/spec); [Markforged blog](https://markforged.com/resources/blog/introducing-job-requests-in-eiger-efficient-management-of-print-requests).

### Inferences
- For PartCAD's `pc cam` G-code, the direct-to-printer path that is open, documented and needs no account is: **OctoPrint, Moonraker (which covers Klipper printers, among them Creality's K2 series and the Snapmaker U1) and PrusaLink**. Each is one HTTP call to upload and start, plus a status GET. A client is protocol-only, so no AGPL or GPL code needs to be imported. This follows the "never import, talk to it" line of `additive.md` §12.4.
- Bambu has three sanctioned routes:
  - **Bambu Connect**: hand it a `.gcode.3mf` through a URL scheme. It needs the desktop app, and the user clicks to confirm.
  - **Developer Mode**: MQTT plus FTPS, unsupported by Bambu, LAN-only, with the cloud lost.
  - **Fleet Hub**: business only, with developer activation.

  All three require a **`.gcode.3mf`**, not plain G-code. An integration that uses Bambu's cloud is contractually off-limits and has drawn legal threats.
- Remote access, for a friend's printer or a makerspace's, is not part of any of the open LAN APIs. It comes from a farm or cloud layer (section 2), from Prusa Connect (no public upload API), or from a tunnel or VPN.
- Summary of what each takes (from the findings above):

| Target | Accepts PartCAD's route as-is | File wrapper needed | Auth | Remote |
| --- | --- | --- | --- | --- |
| OctoPrint 2.0 | yes | `.gcode` (else 415) | Bearer key | LAN; plugins/tunnels |
| Moonraker/Klipper | yes | `.gcode` | none or API key | LAN |
| PrusaLink | yes | `.gcode` / `.bgcode` + `M862.x` checks | Digest (per spec) | LAN |
| Prusa Connect | only via UI or the mobile gateway (no upload in its OpenAPI) | - | account JWT | cloud |
| Bambu (Connect / Dev Mode / Fleet Hub) | yes, if wrapped | `.gcode.3mf` with matching `printer_model_id` | access code / app / mTLS cert | LAN only (cloud closed) |
| UltiMaker DF | yes | `.gcode` or UFP | DF account | cloud |
| Formlabs | no (meshes to `.form`) | - | local / Dashboard login | LAN + Dashboard |
| Markforged Eiger | no (Eiger slices) | - | access key + secret | cloud |

### Gaps
- OctoPrint 2.0's full auth options: whether `X-Api-Key` is still accepted next to Bearer. The files page showed only Bearer.
- PrusaLink's API-key header: the OpenAPI spec defines only Digest. Prusa's firmware may accept `X-Api-Key` as well, but no source was found.
- The current Bambu wiki text (it refused automated fetches), the current Developer Mode availability on H2D/H2S/P2S/X2D firmware, and Fleet Hub's price and US/EU availability.
- Creality Cloud, Anycubic Cloud and Elegoo Cloud: no public job-submission API was found for any of them. The "Elegoo Link" SDK was not verified.
- The exact Markforged Eiger build-upload endpoint, and whether Eiger accepts anything but CAD/STL. UltiMaker Digital Factory's auth model (OAuth scopes or tokens) was not read.
- Snapmaker's older 2.0 HTTP API and Flashforge's LAN API were not researched.

## 2. Print-farm software with job APIs, and whether outsiders can submit to someone else's farm

### Takeaway
Every major farm manager (SimplyPrint, Printago, 3DPrinterOS, FDM Monster, Repetier-Server, Obico, AutoFarm3D, Bambu
Farm Manager/Fleet Hub) has a job API, and Printago and SimplyPrint have well-documented ones. They are all built for
the farm's own operator and its own sales channels (Shopify, Etsy and others). No marketplace was found where an outside
client submits a pre-sliced G-code to a third party's farm by API. The closest mechanisms are:
- a farm issuing an outsider a scoped key or OAuth grant (Printago key permissions, SimplyPrint OAuth2 and approval
  queue);
- Slant 3D's API, which takes models, not G-code.

### Cited Findings
- **SimplyPrint**
  - Auth is an `X-API-KEY` that is per-user and inherits that user's permissions, or **OAuth2** for third-party apps, provisioned through a request form.
  - Plans: "Pro and above unlocks API access". Webhooks need Print Farm or above. Rate limits are 60/min on Pro, 180/min on Print Farm and School, and 600/min on Enterprise.
  - Queue: `queue/AddItem`, with approve, deny and pending-approval endpoints.
  - Printers covered: Prusa through a firmware-side integration, Bambu through a direct connection, plus Creality, Anycubic, Elegoo, OctoPrint and Klipper.

  — [SimplyPrint API](https://simplyprint.io/features/api.md). Uploads go to `files.simplyprint.io`, which returns a token. `printers/actions/CreateJob` starts a job from a file or queue item — [Activepieces SimplyPrint integration (via search)](https://www.activepieces.com/mcp/simplyprint); [SimplyPrint help](https://help.simplyprint.io/en/article/adding-items-to-the-print-queue-files-plates-custom-fields-and-the-api-5aht3p/).
- On Bambu, SimplyPrint needs its **Bambu Lab Client bridge on the LAN, with the printer in LAN-only mode and Developer Mode**, which it calls "the supported path on current Bambu firmware". In cloud mode it can only monitor: "cannot start prints from SimplyPrint" — [SimplyPrint Bambu Lab API](https://simplyprint.io/features/api/bambu-lab-api).
- **Printago**
  - Auth is `authorization: ApiKey <key>` against base `https://api.printago.io`. The limit is 600 requests per hour per store, and a commercial account is required.
  - Endpoints: `POST /v2/builds` (queue parts/SKUs), `POST /v1/orders`, `GET /v1/print-jobs`, and pause/resume/cancel/retry.
  - Telemetry comes over MQTT (`stores/{storeId}/printer-stats/#`). LAN camera streams from its "Fuse" bridge on port 1984 "have no authentication".
  - Integrations: Shopify, Etsy, eBay, Wix, WooCommerce and TikTok Shop.

  — [Printago developers llms.txt](https://developers.printago.io/llms.txt). Separate endpoints exist for `send-to-printer` and permissions such as `queue.view` and `queue.manage` — [Printago API](https://developers.printago.io/post/v1/print-jobs/:id/send-to-printer); [print-jobs/:id](https://developers.printago.io/get/v1/print-jobs/:id).
- Printago slices in the cloud with Orca or Bambu Studio. It "accepts STL, STEP, 3MF, OpenSCAD, ColorSCAD, **CadQuery, build123d**, and pre-sliced .gcode.3mf files", and sends pre-sliced `.gcode.3mf` "to the assigned printer unchanged". Its docs warn that such files have "printer-specific settings baked into the G-code, no geometry data", and that part settings must match the allowed filaments and printer types — [Printago Orca Slicer page](https://printago.io/features/orca-slicer); [Printago docs, gcode.3mf](https://docs.printago.io/docs/parts/gcode-3mf-files).
- **3DPrinterOS** has a Global API v2.1 with file upload, job lists and pause/resume/cancel. Its "Start print job" endpoint is marked **[in development]**. In the web UI, users slice in the cloud or upload `.gcode` or `.stl` — [3DPrinterOS Global API v2.1](https://intercom.help/3DPrinterOS/en/articles/13516944-3dprinteros-global-api-calls-v2-1); [How to submit a print job](https://intercom.help/3DPrinterOS/en/articles/9681380-how-to-submit-a-print-job-in-3dprinteros).
- **FDM Monster** is AGPL-3.0-or-later and manages OctoPrint, Moonraker, PrusaLink and Bambu Lab instances. Its latest release is 2.1.1 (15 May 2026). One source calls OctoFarm, its ancestor, dead since 2023 — [FDM Monster release notes](https://unpkg.com/@fdm-monster/server@2.1.1/RELEASE_NOTES.MD); [README](https://unpkg.com/@fdm-monster/server@2.1.1/README.md); [printer-hub blog](https://printer-hub.ru/en/posts/3d-print-farm-server-setup).
- **Repetier-Server** (commercial):
  - Upload: `POST /printer/model/<slug>?a=upload` as multipart.
  - Start: `copyModel` with `autostart=true`, which "works only if no job is running", otherwise the model is queued.
  - Auth: an `apikey` parameter or a session.

  — [Repetier-Server API manual](https://www.repetier-server.com/manuals/programming/API/index.html); [Repetier forum](https://forum.repetier.com/discussion/comment/44736).
- **Obico** is AGPL-3.0 — [obico-server LICENSE](https://raw.githubusercontent.com/TheSpaghettiDetective/obico-server/release/LICENSE). Its OAuth "printer management" API has `POST /api/v1/printers/{id}/start_print/` — [Obico OAuth printer management](https://www.obico.io/docs/developer-guides/oauth-printer-management/). Whether that call starts a physical print or records a print session is *unverified*. Remote start and G-code upload are Pro-plan features — [Obico Klipper](https://obico.io/klipper.html).
- **3DQue AutoFarm3D**: no public API docs were found. A competitor says its API is Enterprise-only (*unverified*) — [SimplyPrint vs AutoFarm3D](https://simplyprint.io/alternatives/3dque-autofarm3d.md). It is "fully compatible with Bambu Lab Developer Mode" — [3D Printing Industry](https://3dprintingindustry.com/news/3dques-autofarm3d-now-fully-compatible-with-bambu-lab-developer-mode-241187/).
- **Bambu Farm Manager** is free Windows software with a 24/7 server and a client, LAN-based, for X1C, P1S, P1P, A1 and A1 mini (via search snippet). Users report that it still communicates with the cloud — [Bambu blog, Farm Manager](https://blog.bambulab.com/bambu-lab-introduces-local-fleet-control-with-bambu-farm-manager/); [Bambu forum](https://forum.bambulab.com/t/better-lan-only-mode-support/255943). Fleet Hub (section 1) is the API product.
- **AstroPrint**: a competitor says it changed owners to BCN3D and then to Print&Go in 2024 (*unverified*) — [SimplyPrint, AstroPrint alternative](https://simplyprint.io/hi/alternatives/astroprint). **Polar Cloud** is still active, with a 2025 redesign — [Polar3D blog](https://polar3d.com/blog/ui-redesign-2025).
- **Prusa Connect** can manage individual printers or groups in a farm — [Prusa help](https://help.prusa3d.com/en/article/sending-g-codes-to-printer-via-network-prusaconnect-prusalink-octoprint_196761) — and it has teams (`GET /api/v1/teams` in the mobile gateway above).
- **FarmLoop (3D Farmers) Processing API**:
  - `POST https://api.3d-farmers.com/api/v1/process`, with `X-API-Key: fl_...`, on the Business plan.
  - Takes `.gcode.3mf`, sliced `.3mf`, `.gcode` and `.bgcode`, and returns `.bgcode` as plain `.gcode`. Limits: 200 MB, 10 req/5 min, 3 concurrent jobs.
  - Returns "the FarmLoop-modified file back ... with the detachment sequences injected". OrcaSlicer files are not supported.

  — [FarmLoop Processing API](https://help.3d-farmers.com/integrations/processing-api/).
- **Slant 3D** launched an API in beta in 2024. Models are uploaded to a cloud library and Slant prepares, prints and ships them. Orders are drafted and then processed, from a `file_id` or STL URL (per a third-party wrapper) — [Fabbaloo](https://www.fabbaloo.com/news/slant-3d-launches-api-for-direct-access-to-print-farms); [3printr](https://www.3printr.com/slant-3d-launches-beta-phase-for-3d-printing-api-1870594/); [AGPT Slant3D blocks](https://agpt.co/docs/integrations/block-integrations/order/).
- A broad search for a print-farm marketplace taking jobs by API surfaced no such marketplace, only self-hosted farm interfaces, FarmLoop and Printago — [search results incl. Printago send-to-printer](https://developers.printago.io/post/v1/print-jobs/:id/send-to-printer).

### Inferences
- Printago is the closest fit to PartCAD's model among the farm tools. It already ingests **CadQuery and build123d** sources and slices them itself, and it also passes a pre-sliced `.gcode.3mf` through unchanged. A PartCAD integration could do either. Only the second preserves "the validated route", and only on Bambu-class printers through `.gcode.3mf`.
- How a makerspace or friend's farm could take a PartCAD job today:
  - Give the user a SimplyPrint account or OAuth grant whose queue items need approval.
  - Or give them a Printago API key scoped to `queue.*`.
  - In both cases the farm's queue matches the job to a printer whose type and filament fit.

  Neither product presents this as a customer-intake feature (the SimplyPrint page frames approval as an internal control).
- Automated-ejection farms (FarmLoop, AutoFarm3D-style) **modify the G-code by design**, by appending or injecting detachment sequences. A farm can therefore honestly say it runs a customer's route unmodified only for the part body. The start, end and ejection code is the farm's.

### Gaps
- No public API docs were found for AutoFarm3D, Bambu Farm Manager, or Prusa Connect job upload.
- The exact `apidocs.simplyprint.io` upload schema and the file types SimplyPrint accepts (`.bgcode`, `.gcode.3mf`) were not read.
- No evidence was found of any marketplace (Printago, SimplyPrint, Craftcloud-like) routing G-code jobs between independent farms by API. If one exists, it was not found.
- Polar Cloud's and 3DPrinterOS's job-submission terms for outside users (universities use 3DPrinterOS for student submissions, but the API's start endpoint is still "in development").

## 3. Interchange formats that carry an exact print, and how printer-specific they are

### Takeaway
In practice an exact print travels as **plain G-code** (OctoPrint, Moonraker, PrusaLink, UltiMaker),
**Prusa `.bgcode`** (a lossless binary container for the same G-code, under AGPL-3.0 reference code), or **Bambu's
`.gcode.3mf`** (plate G-code plus config files inside an OPC package). Bambu's firmware rejects a `.gcode.3mf` with
missing keys, wrong-length arrays or a mismatched `printer_model_id`. Prusa's firmware checks printer model and nozzle
through `M862.3` / `M862.1` lines, with a user setting of none, warn or strict. The 3MF Toolpath extension 1.0.0
(published 3 September 2026) is laser-first. For extrusion it standardises only `depositionspeed`, `beadwidth` and
`beadheight`, so temperature, fan, retraction and flow need a vendor namespace. lib3mf 2.5.0 does not implement it, and
no printer or slicer reader was found.

### Cited Findings
- **Binary G-code (`.bgcode`)**: the reference library `prusa3d/libbgcode` is **AGPL-3.0** — [libbgcode LICENSE](https://raw.githubusercontent.com/prusa3d/libbgcode/main/LICENSE). The format is a file header, then blocks of header, parameters, data and an optional CRC32. Compression is none, Deflate, Heatshrink 11/4 or Heatshrink 12/4. Integers are little-endian. The spec is `doc/specifications.md` — [Debian libbgcode specifications.md](https://sources.debian.org/src/libbgcode/0.0~git20260306.c019e78-1/doc/specifications.md); [binarygcode crate (Rust, MIT)](https://docs.rs/crate/binarygcode/0.0.3/source/README.md). Prusa's help page — [Binary G-code](https://help.prusa3d.com/article/binary-g-code_646763).
- **Prusa compatibility checks**: `M862.3 P"<model>"` (printer model) and `M862.1` (nozzle diameter). Each check can be set to none, warn or strict on the printer. Under strict, "the user can't continue until he fixes the issue, and print is aborted" — [Prusa G-code reference](https://help.prusa3d.com/article/prusa-firmware-specific-g-code-commands_112173); [HW setup menu](https://help.prusa3d.com/en/article/hw-setup-menu_1943). A firmware update that switched on the "Nozzle High Flow" setting made existing G-code "not fully compatible" (anecdotal) — [Prusa forum](https://forum.prusa3d.com/forum/english-forum-original-prusa-i3-mk4-hardware-firmware-and-software-help/g-code-isnt-fully-compatible-message-after-upgrading-firmware-to-6-5-3/).
- **Bambu `.gcode.3mf`** contains:
  - `Metadata/plate_1.gcode`;
  - `Metadata/slice_info.config`, `project_settings.config` and `model_settings.config`;
  - `Metadata/plate_1.png`;
  - `3D/3dmodel.model`, `[Content_Types].xml` and `_rels/.rels`.

  "All files include MD5 checksums validated by the printer firmware". The firmware "rejects archives where keys are missing, arrays are the wrong length, or the embedded `printer_model_id` doesn't match". The P1S model ID is `C12` — [bambox on PyPI](https://pypi.org/project/bambox/0.4.6/). Users report "Incompatible printer model" and "not sliced for this printer" errors when the printer, process or nozzle profiles disagree, and the fix is to export the *sliced plate* rather than the project — [Bambu forum](https://forum.bambulab.com/t/print-from-sd-card-incompatible-printer-model/199519); [Bambu forum](https://forum.bambulab.com/t/printer-is-not-compatible-with-the-process-preset-in-the-3mf/123861).
- The `project_file` command selects the plate G-code by `param: Metadata/plate_N.gcode` and checks `md5` — [OpenBambuAPI](https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md). Fleet Hub accepts only `gcode.3mf` and indexes files by MD5 — [Fleet Hub white paper](https://portal.bblmw.com/fleet-hub/wb76oog4i8k/files/Fleet%20Hub%20Technical%20White%20Paper%20EN%20v1.01.pdf).
- Other formats:
  - OctoPrint accepts only `gcode` or `stl` (415 otherwise) — [OctoPrint files API](https://docs.octoprint.org/en/master/api/files.html).
  - UltiMaker takes G-code or UFP — [UltiMaker API docs](https://docs.api.ultimaker.com/guides/print-job-tracking.html).
  - Formlabs prints only from a PreForm scene / `.form` — [Formlabs Local API](https://formlabs-dashboard-api-resources.s3.us-east-1.amazonaws.com/formlabs-local-api-v0.8.9.html).
  - FarmLoop converts `.bgcode` to plain `.gcode` on output — [FarmLoop](https://help.3d-farmers.com/integrations/processing-api/).
- **3MF Toolpath extension** (`spec_toolpath`):
  - **Status:** the change history reads "1.0.0 | First published version | September 3, 2026", while the header still says "Status: Release Candidate" and the repo README says "Draft for 3MF's lasertoolpath extension".
  - **Scope:** "laser based technologies, with provisions for future use in deposition". It lists FFF among the planar technologies and defines 3-axis and 6-axis polylines for non-planar deposition.
  - **Deposition profile:** the standard attributes are only `depositionspeed`, `beadwidth`, `beadheight`, plus `prewaittime` / `postwaittime`. The laser profile has `laserpower`, `laserspeed`, `jumpspeed`, `laserfocus`, `spotradius` and `laserindex`.
  - **Machine-specific profiles** must be namespaced, and a consumer meeting an unrecognised namespace declared *required* "MUST reject the job".
  - **Storage:** layers are separate OPC XML parts.

  — [3MF Toolpath Extension.md (raw)](https://raw.githubusercontent.com/3MFConsortium/spec_toolpath/master/3MF%20Toolpath%20Extension.md); [repo](https://github.com/3MFConsortium/spec_toolpath).
- Trade press frames the November 2026 release as improving **metal** 3D printing interoperability — [All3DP](https://all3dp.com/6/3mf-consortium-releases-open-toolpath-extension-to-improve-metal-3d-printing-interoperability/). AI Build joined the consortium in March 2025 to work on multi-axis toolpaths — [3MF news](https://3mf.io/news/2025/03/ai-build-join-the-3mf-consortium-to-help-develop-the-toolpath-extension-for-multi-axis-3d-printing/).
- **lib3mf 2.5.0** (PyPI, 2026-02-23, BSD) is the newest release. Its Python binding (`lib3mf/Lib3MF.py`) contains **no "Toolpath" class or mention** (checked directly in the wheel) — [PyPI lib3mf](https://pypi.org/project/lib3mf/).

### Inferences
- A farm, or a host, can check that a job fits a printer from the metadata the formats already carry:
  - printer model (`M862.3` / `printer_model` comments; Bambu's `printer_model_id`);
  - nozzle diameter (`M862.1`; Bambu nozzle fields);
  - filament type per extruder or AMS slot (`slice_info.config`; Printago's "allowed filaments");
  - bed and plate type;
  - firmware features the G-code needs (Prusa input-shaper G-code errors on firmware older than 4.6.2; see section 4).

  PartCAD's route writer would need to emit these to be accepted, and a `.gcode.3mf` wrapper for Bambu (bambox shows this is doable in Python, MIT).
- The 3MF Toolpath extension cannot today carry a complete FFF print that a farm could run. It lacks standard temperature, fan, retraction and extrusion-rate fields, and nothing reads it. For PartCAD it remains an *archival or validation* format for the route (bead width and height per segment), as §7.4 suggests, not a delivery format.

### Gaps
- No source confirmed which printers or slicers consume the 3MF **Slice** extension today, or whether any FFF firmware reads Toolpath 3MF.
- AMF was not researched further: no printer or farm API found accepts it.
- The full list of `slice_info.config` keys Bambu firmware requires per model was not found in a primary source; bambox's page names only `printer_model_id`.
- Whether Moonraker or OctoPrint accept `.bgcode` natively (not stated in their docs).

## 4. Guaranteeing "the delivered print = the validated print"

### Takeaway
Shipping an unmodified G-code fixes the toolpath, but not what the printer does with it:
- Firmware applies its own input shaping and pressure advance unless the G-code sets them explicitly.
- Bambu printers run flow and vibration calibration at job start if the job asks for it.
- Farms routinely prepend or append their own start, end and ejection code.

A guarantee therefore needs the G-code to pin every compensation it depends on, a named printer model and firmware
range, a filament, and a farm commitment not to alter it. No farm software or service was found that makes that
commitment as a product feature.

### Cited Findings
- **Prusa (Buddy firmware 5.0+)**:
  - `M572` sets pressure advance; "the latest command, either M900 (converted 1:1) or M572" wins, and `S0` disables it.
  - `M593` sets input-shaper parameters, and "the profiles and frequencies are built-in the code, no user calibration is needed".
  - Changing either during a print makes the printer decelerate to zero velocity.
  - Older firmware (4.6.2) raises an error on input-shaper G-code.

  — [Prusa help, Pressure Advance](https://help.prusa3d.com/article/pressure-advance_814986); [Prusa forum, FW 5.0.0-alpha1 notes](https://forum.prusa3d.com/forum/input-shaping/firmware-5-0-0-alpha1?language=de). The help page and the alpha notes disagree on whether `M572 W` (smoothing) is honoured — [same](https://help.prusa3d.com/article/pressure-advance_814986).
- **Klipper**: pressure advance and input shaper default to `printer.cfg` and can be overridden from G-code with `SET_PRESSURE_ADVANCE` and `SET_INPUT_SHAPER`, the latter only if `[input_shaper]` is configured — [Klipper G-Codes](https://www.klipper3d.org/G-Codes.html).
- **Bambu**: the `project_file` start command carries `bed_levelling`, `flow_cali` (flow dynamics calibration), `vibration_cali` and `layer_inspect` flags, plus an `ams_mapping` from the job's filaments to AMS slots. A wrong mapping makes the printer pause — [OpenBambuAPI](https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md). Fleet Hub also exposes "modifying filaments" alongside print control — [Fleet Hub white paper](https://portal.bblmw.com/fleet-hub/wb76oog4i8k/files/Fleet%20Hub%20Technical%20White%20Paper%20EN%20v1.01.pdf).
- **Farm practice**:
  - Printago sends pre-sliced `.gcode.3mf` unchanged, but notes that such files have printer-specific settings baked in and must match the printer type and filament — [Printago Orca page](https://printago.io/features/orca-slicer); [docs](https://docs.printago.io/docs/parts/gcode-3mf-files).
  - FarmLoop's API exists to inject detachment sequences into the customer's file — [FarmLoop](https://help.3d-farmers.com/integrations/processing-api/).
  - AutoFarm3D refuses to dispatch a job to a printer without enough filament, and routes jobs by printer type — [Fabbaloo](https://www.fabbaloo.com/news/3dque-offers-automated-3d-printing-on-many-3d-printer-models); [DE247](https://www.digitalengineering247.com/article/3dque-debuts-autofarm-automated-command-center/additive-manufacturing).
- Firmware updates change acceptance. Users report model-check failures after Prusa firmware updates, and a firmware update toggling the high-flow nozzle setting (anecdotal) — [Prusa forum](https://forum.prusa3d.com/forum/original-prusa-i3-mk3s-mk3-hardware-firmware-and-software-help/fw-update-bug-model-was-sliced-for-another-printer-model); [Prusa forum](https://forum.prusa3d.com/forum/english-forum-original-prusa-i3-mk4-hardware-firmware-and-software-help/g-code-isnt-fully-compatible-message-after-upgrading-firmware-to-6-5-3/). Fleet Hub lists a minimum firmware for each model — [white paper](https://portal.bblmw.com/fleet-hub/wb76oog4i8k/files/Fleet%20Hub%20Technical%20White%20Paper%20EN%20v1.01.pdf).

### Inferences
- To make "validated = delivered" checkable, a job could carry the following alongside the G-code:
  - (a) the printer model and its firmware range;
  - (b) nozzle diameter and type;
  - (c) filament material, brand or density, and temperatures;
  - (d) every compensation the validation assumed, emitted as explicit commands in the G-code (`M572`/`M593` on Prusa, `SET_PRESSURE_ADVANCE`/`SET_INPUT_SHAPER` on Klipper; Bambu's own calibrations disabled or recorded through the `project_file` flags);
  - (e) a hash of the route section.

  A host could then verify the body hash and that only farm-owned start, end and ejection blocks differ.
- Remaining physical variance is not in the file and has to be validated as tolerance, not eliminated: e-steps and flow calibration, actual nozzle wear, filament lot, and ambient conditions.
- Whether a farm would *commit* to running an unmodified customer G-code on a named printer model is a contractual or business question. The software supports it (Printago pass-through, Fleet Hub, Moonraker, PrusaLink, OctoPrint), but no published offer was found.

### Gaps
- No published farm or service policy was found that guarantees unmodified customer G-code on a named model. The other researcher's notes on G-code-accepting services should be checked.
- No source quantified print-to-print variation from firmware compensations alone.
- Bambu's per-filament flow (K) handling when `flow_cali` is off was not documented in a primary source.

## 5. Open-source Python libraries for these APIs, and their licences

### Takeaway
Permissively licensed clients exist for Bambu (`bambulabs-api` MIT, `pybambu` Apache-2.0, `ha-bambulab` MIT), PrusaLink
(`pyprusalink` Apache-2.0, `PrusaLinkPy` MIT), OctoPrint (`octorest` MIT, old), and Elegoo (`pycentauri` Apache-2.0). The
Moonraker clients (`moonraker-api`, `moonraker-client`) are GPL-3.0. The Bambu cloud client is AGPL-3.0 and targets a
cloud Bambu forbids third parties to use, and libbgcode is AGPL-3.0. For an Apache-2.0 project, writing the few HTTP
calls directly is simpler than importing the copyleft ones.

### Cited Findings
Versions and licences are from PyPI's JSON API as of 2026-11-22 unless noted.
- `octorest` 0.4, MIT, an OctoPrint REST client — [PyPI](https://pypi.org/project/octorest/); [GitHub](https://github.com/dougbrion/OctoRest).
- `moonraker-api` 4.1.0, **GPLv3**, an async WebSocket client — [PyPI](https://pypi.org/project/moonraker-api/). `moonraker-client` 0.2.0, **GPL-3.0** — [PyPI](https://pypi.org/project/moonraker-client/).
- `pyprusalink` 3.1.0, Apache-2.0, "Library to interact with PrusaLink v2" (used by Home Assistant) — [PyPI](https://pypi.org/project/pyprusalink/). `PrusaLinkPy` 2.2.1, MIT — [PyPI](https://pypi.org/project/PrusaLinkPy/).
- `prusa-connect-sdk-printer` 0.8.1, "Freeware", printer-side — [PyPI](https://pypi.org/project/prusa-connect-sdk-printer/).
- Bambu clients:
  - `bambulabs-api` 2.6.6, MIT, MQTT — [PyPI](https://pypi.org/project/bambulabs-api/); [LICENSE](https://raw.githubusercontent.com/acse-ci223/bambulabs_api/main/LICENSE).
  - `pybambu` 1.0.1, Apache-2.0 — [PyPI](https://pypi.org/project/pybambu/).
  - `ha-bambulab`, MIT — [LICENSE](https://raw.githubusercontent.com/greghesp/ha-bambulab/main/LICENSE).
  - `bambu-connect` 0.3.1, MIT, an MQTT and camera client unrelated to Bambu's app of the same name — [PyPI](https://pypi.org/project/bambu-connect/).
  - `bambu-lab-cloud-api` 1.0.5, **AGPL-3.0**, covering cloud, MQTT and local — [PyPI](https://pypi.org/project/bambu-lab-cloud-api/).
- `bambox` (MIT) packages plain G-code into `.gcode.3mf`. Its bundled profiles are derived from AGPL OrcaSlicer and Bambu Studio sources. It sends only through a cloud bridge, and LAN-direct is "not yet available" — [PyPI bambox](https://pypi.org/project/bambox/0.4.6/).
- `pycentauri` 0.9.1, Apache-2.0, for the Elegoo Centauri Carbon over LAN (not the CC2) — [PyPI](https://pypi.org/project/pycentauri/).
- `simplyprint` 4.2.3, AGPLv3. This appears to be SimplyPrint's printer-side client, and SimplyPrint's REST API has no official Python SDK in this search — [PyPI](https://pypi.org/project/simplyprint/).
- Formlabs publishes `formlabs-api-python` and the `formlabs_preform_api` wheel. No licence is stated, and neither is on PyPI under those names — [Formlabs release notes](https://formlabs.com/support/Formlabs-API-downloads-and-release-notes/).
- `lib3mf` 2.5.0, BSD, with no Toolpath support — [PyPI](https://pypi.org/project/lib3mf/). `libbgcode` is AGPL-3.0, and neither `libbgcode` nor `pybgcode` is on PyPI — [LICENSE](https://raw.githubusercontent.com/prusa3d/libbgcode/main/LICENSE). `binarygcode` is MIT, in Rust — [docs.rs](https://docs.rs/crate/binarygcode/0.0.3/source/README.md).
- Server and host software licences: OctoPrint is AGPL-3.0-or-later ([PyPI](https://pypi.org/pypi/OctoPrint/json)); Moonraker is GPL-3.0 ([LICENSE](https://raw.githubusercontent.com/Arksine/moonraker/master/LICENSE)); PrusaLink Web's spec is AGPLv3 ([openapi.yaml](https://raw.githubusercontent.com/prusa3d/Prusa-Link-Web/master/spec/openapi.yaml)); Obico server is AGPL-3.0 ([LICENSE](https://raw.githubusercontent.com/TheSpaghettiDetective/obico-server/release/LICENSE)); FDM Monster is AGPL-3.0-or-later ([FDM Monster](https://unpkg.com/@fdm-monster/server@2.1.1/README.md)).

### Inferences
- Under the reasoning in `additive.md` §12.4, talking HTTP or MQTT to an AGPL or GPL host is communication between programs. Importing a GPL client library (`moonraker-api`) or the AGPL `libbgcode` / `bambu-lab-cloud-api` into the Apache-2.0 wheel is not.
- The OctoPrint, Moonraker and PrusaLink calls are each a handful of HTTP requests, and could be written directly in `partcad_client`. They act on the user's own machine and network, consistent with the CLAUDE.md rule that a client, not a daemon, reaches local hardware.
- `bambulabs-api` and `pybambu` (MIT and Apache-2.0) are usable for Bambu Developer-Mode LAN control. Fleet Hub needs Bambu-issued certificates and an agreement, and so cannot be a generic open-source feature.

### Gaps
- No official Python SDK was found for SimplyPrint, Printago (OpenAPI is available at `/swagger.json` for generation), Prusa Connect, UltiMaker Digital Factory or Markforged Eiger.
- The licence of Formlabs' Python client is not stated.
- Maintenance status beyond the version numbers (last release dates for `octorest` and `pybambu`) was not checked.
