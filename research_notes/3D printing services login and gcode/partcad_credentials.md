# PartCAD `pc login` and plugin credentials, as the code has them — and what that means for 3D-printing-service `manufacturer` plugins

Citation conventions: a relative link such as `src/partcad_cli/click/commands/login.py#L158` is a path in the PartCAD
checkout `/home/user/partcad` at commit `499c5d9afcb3e7c30fa75fede9a0a94dd6de3a97` (branch
`claude/sharp-ramanujan-d10cf2`), cited as `file:line`. Plugin repositories were cloned from `github.com/partcad/*`
(all 17 clones succeeded) and are cited by commit-pinned GitHub URLs. The index (`/home/user/partcad-index`) `main`
and `devel` were both at `40d113d4e1d1238172c9c9c458311b6f67bb604e` when fetched, so "the index" below means both.
Nothing was executed against PartCAD itself: the checkout has no `.venv`, so every behavioural claim is from reading
code; the one place a behaviour was simulated is marked.

## 1. The credential lifecycle end to end: sources, storage, delivery, the daemon/sandbox boundary, exposure

### Takeaway
A plugin credential is nothing but an ordinary *plugin parameter* whose value the user overrides: `pc login` gets it
(browser extension capture, the manual page, `--set`, or the MCP tool's `values`), the *client* writes it in plaintext
into `~/.partcad/config.yaml` under `parameters:` (0600, atomic replace, file lock), and every later command ships the
client's whole resolved config — credentials included — to the daemon with `context.create`; the daemon folds the
override into the parameter's `default`, which goes into `request["parameters"]` on the plugin's stdin in whatever
sandbox runs it. Redaction covers `git.auth`, `remoteSandboxToken`, the `user` section and `PC_*TOKEN*`-style env
vars — but, by my reading, **not** `parameters:`, so `pc config` / `pc system status config` / `pc daemon status
config` print saved plugin credentials verbatim.

### Cited Findings

**Where a credential can come from**
- The plugin's `login` api runs in the daemon's sandbox; PartCAD injects `partcad_login` only for `api == "login"`
  and `partcad_user` for every api — [src/partcad/wrappers/wrapper_plugin.py:26-40](src/partcad/wrappers/wrapper_plugin.py#L26).
- `partcad_login.open_browser(url, capture, title, guide, require, done_when, timeout, instructions)` is the only
  callback; capture sources are exactly `cookie`, `localStorage`, `sessionStorage`, `dom`, `redirect`, `ask`
  (one per capture, validated in the plugin's own run) — [src/partcad/wrappers/plugin_login.py:43, 149-237](src/partcad/wrappers/plugin_login.py#L43); documented in [docs/source/plugins/login.rst:77-117](docs/source/plugins/login.rst#L77).
  - `cookie` is read "with the browser's cookie API, HttpOnly cookies included"; `redirect` reads the query/fragment
    of an address matching a pattern ("how an OAuth implicit grant hands its token over; the page need not load");
    `ask` is an input in the extension banner — [docs/source/plugins/login.rst:86-92](docs/source/plugins/login.rst#L86).
  - `match` regexes must be readable identically by Python and JS (no `(?i)`, `(?P<>)`, `\A`, possessives); checked
    in Python before the browser is sent — [src/partcad/wrappers/plugin_login.py:83-139](src/partcad/wrappers/plugin_login.py#L83).
  - Timeout clamped to 10..3600 s, default 600 — [plugin_login.py:46-50, 229](src/partcad/wrappers/plugin_login.py#L46).
- The callback is a **replay**: first call raises `BrowserNeeded` (a `BaseException`, so a plugin's `except Exception`
  does not swallow it), the client opens the browser, then `login` is re-run from the top and the n-th call returns
  the n-th result — [plugin_login.py:27-37, 53-58, 292-305](src/partcad/wrappers/plugin_login.py#L27); wrapper turns
  the exception into `{"browser": spec}` / `{"instructions": spec}` — [wrapper_plugin.py:48-61](src/partcad/wrappers/wrapper_plugin.py#L48).
- Non-interactive (`pc login --agent` / MCP): `open_browser` raises `InstructionsNeeded`; the CLI prints where to sign
  in, each capture's name and where it is found, the plugin's `instructions`, and `pc login --agent <plugin> --set
  name=<name>`, exiting with status 3 — [src/partcad_cli/click/commands/login.py:12-14, 144-156](src/partcad_cli/click/commands/login.py#L144); text built by [src/partcad_client/login.py:259-294](src/partcad_client/login.py#L259).
- `--set NAME=VALUE` (repeatable) answers the matching `open_browser` call directly "in either mode", and the plugin
  checks it like browser-captured values — [login.py:59-66, 104-117](src/partcad_cli/click/commands/login.py#L59); [plugin_login.py:262-291](src/partcad/wrappers/plugin_login.py#L262) (empty values are dropped at :259).
- MCP `login` tool: `values: {name: secret}` passed by the agent; opens a browser only if `interactive=true`
  ("only when the user says they are at its screen") — [src/partcad_client/mcp_server/server.py:700-760](src/partcad_client/mcp_server/server.py#L700).
- Manual fallback: the 127.0.0.1 listener serves a page with one `<input>` per capture (`type=password` when `secret`
  or not an `ask`, `autocomplete=off`) submitted by `<form method='get'>` to the step's `done` URL — [src/partcad_client/login.py:216-237](src/partcad_client/login.py#L216).
- Environment variables: the `plugin_models` toolkit's `credential()` reads `request["parameters"][name]`, else
  `os.environ[ENV]` — [src/partcad/wrappers/plugin_models.py:568-575](src/partcad/wrappers/plugin_models.py#L568);
  `Site.CREDENTIALS = {param: ENV_VAR}` — [plugin_models.py:1014-1020](src/partcad/wrappers/plugin_models.py#L1014). The
  toolkit itself warns the env var is not seen by a container sandbox — [plugin_models.py:1038-1052](src/partcad/wrappers/plugin_models.py#L1038); same warning in [partcad-repo-grabcad README:135-138](https://github.com/partcad/partcad-repo-grabcad/blob/55f8e38bf39b005dd8ffef6e8b6556adb463d48f/README.md#L135).
- Hand-edited config / `--extra-param`: any declared provider parameter can be set under `parameters: <full plugin
  name>:` in `~/.partcad/config.yaml` — [docs/source/config_making.rst:1414-1427](docs/source/config_making.rst#L1414).

**The browser side (client machine only)**
- Default browser, but in a PartCAD-only profile under `~/.partcad/browser/<browser>/`, kept between logins "so a site
  signed in to once stays signed in, and the next `pc login` is often over before the window is drawn" —
  [src/partcad_client/browser.py:13-28](src/partcad_client/browser.py#L13). Chromium gets the unpacked extension via
  the DevTools pipe (`Extensions.loadUnpacked`), Firefox via WebDriver BiDi temporary add-on — [browser.py:30-38](src/partcad_client/browser.py#L30).
- Listener: `127.0.0.1`, OS-chosen port, per-step random nonce (`secrets.token_hex(16)`), requests with a `Host` other
  than 127.0.0.1/localhost refused (anti-DNS-rebinding), no request logging, `Cache-Control: no-store`,
  `Referrer-Policy: no-referrer` — [src/partcad_client/login.py:51-70, 91-92, 134-187](src/partcad_client/login.py#L134).
- The extension shows its own confirmation page ("Sign in to … for PartCAD?") naming every value and where it will be
  sent; nothing is captured before **Continue** — [docs/source/plugins/login.rst:165-172](docs/source/plugins/login.rst#L165); [browsers/README.md:97-103](browsers/README.md#L97).
  Captures only on origins the spec names, sends only to its own start page's callback (no cookies, no redirects),
  drops everything at `timeout`, one session at a time, refuses incognito — [browsers/README.md:104-120](browsers/README.md#L104).
  The in-progress login lives in `storage.session` (memory only) — [browsers/README.md:30](browsers/README.md#L30).
  Values reach the listener as a `GET callback?<name>=<value>&...` — [browsers/README.md:46-49](browsers/README.md#L46).
- Bot checks: on a Cloudflare challenge page the banner asks the person to confirm and "the extension never clicks,
  scripts or reads the check" — [browsers/README.md:87-93](browsers/README.md#L87); "a plugin is only ever handed the
  credentials signing in left behind, never anything the check granted the browser" — [docs/source/plugins/login.rst:174-177](docs/source/plugins/login.rst#L174).

**The loop and who writes what**
- The client loop: ask daemon `plugin.login` → if `status == "browser"` start listener, open browser, wait → ask
  again with results; max 5 steps — [src/partcad_client/login.py:300-369](src/partcad_client/login.py#L300).
- Daemon method `plugin.login` resolves `<package>:<plugin>` as a repository or provider, runs
  `plugin.login(browser, check, non_interactive, values)` and answers `done` with **the credential values themselves**
  in `parameters` (plus `package`/`shared` for `shared: true` parameters) — [src/partcad_service_json_rpc/core/operations.py:6285-6373](src/partcad_service_json_rpc/core/operations.py#L6285); registered at [rpc/methods.py:116-117](src/partcad_service_json_rpc/rpc/methods.py#L116).
- `Plugin.login` rejects a result whose parameters are not plain `str/int/float/bool` — [src/partcad/plugin.py:105-157 (check at :151)](src/partcad/plugin.py#L151).
  So a credential must be a scalar; a file credential has to be a path or base64 string (see McMaster-Carr, §3).
- The **client** saves: `save_parameter_overrides(answer["plugin"], parameters, package_name, shared)` unless
  `--check` — [src/partcad_cli/click/commands/login.py:158-176](src/partcad_cli/click/commands/login.py#L158). "The
  daemon still opens nothing and writes nothing" — [src/partcad_cli/AGENTS.md:127-145](src/partcad_cli/AGENTS.md#L127).
- Storage: `~/.partcad/config.yaml`, section `parameters`, round-tripped with ruamel (comments kept), under a
  `FileLock(path + ".lock", timeout=60, mode=0o600)`, written to `<path>.<pid>.tmp` opened `0o600`, `chmod 0o600`,
  then `os.replace` — [src/partcad_utils/user_config.py:1698-1780](src/partcad_utils/user_config.py#L1698). The lock
  exists because "two logins can finish at once — two `pc login`s, or an agent's parallel `login` calls through
  `pc mcp`" — [user_config.py:1719-1723](src/partcad_utils/user_config.py#L1719).
- Shared vs per-plugin: a value is saved under the plugin's full name, unless the plugin's declaration marks the
  parameter `shared: true`, in which case it is saved under the *package* and removed from the package's object
  entries — [src/partcad_utils/parameters.py:433-440, 703-738](src/partcad_utils/parameters.py#L703); docs [docs/source/config_objects.rst:796-888](docs/source/config_objects.rst#L796)
  (the motivating case: "a repository serving its models and a provider ordering from it — needs one API token for both").
- MCP: saves the same way and also patches the MCP server's in-memory config so the next request carries it
  (`bridge.remember_parameters`); the tool result "names" saved parameters and never repeats values — [server.py:788-801](src/partcad_client/mcp_server/server.py#L788); [bridge.py:210-240](src/partcad_client/mcp_server/bridge.py#L210).

**How it reaches the plugin at request time**
- Every CLI command sends `context.create {"url", "userConfig": _user_config.to_dict()}` — the client's resolved
  config, explicitly so a warm daemon uses *this* invocation's config — [src/partcad_cli/click/service.py:61-85](src/partcad_cli/click/service.py#L61).
  `to_dict()` includes the `parameters` and `user` sections (`SECTION_PATHS`) — [user_config.py:722-758, 455-460](src/partcad_utils/user_config.py#L722).
- The daemon builds the context from that copy and keeps the copy itself as the context's fingerprint ("the sent data
  itself rather than a hash of it"); a different copy rebuilds the warm context — [operations.py:2790-2812, 2849-2850](src/partcad_service_json_rpc/core/operations.py#L2790).
  A client that sends no `userConfig` — the VS Code extension — gets the daemon's own config — [operations.py:2806-2811](src/partcad_service_json_rpc/core/operations.py#L2806).
- Overrides are applied only to parameters the object **declares** (an undeclared name is logged at debug and ignored),
  by setting the declaration's `default` — [src/partcad/config.py:23-98 (default set at :93)](src/partcad/config.py#L43).
  The plugin request then carries `request["parameters"][name] = param["default"]` for every declared parameter
  with a default — [src/partcad/plugin_factory_python.py:217-222](src/partcad/plugin_factory_python.py#L217).
- The request (with `parameters`, `userInfo`, and for `manufacturer` providers the full `user` section) is
  serialized and fed to the wrapper on stdin in the sandbox runtime — [plugin_factory_python.py:203-265](src/partcad/plugin_factory_python.py#L203); the `stdin` debug lines in the runtime are commented out — [src/partcad/runtime_python.py:762, 852, 886](src/partcad/runtime_python.py#L762).
- Plugin stderr is reported line by line through PartCAD logging (`plugin.error`) — [plugin_factory_python.py:286-293](src/partcad/plugin_factory_python.py#L286); the toolkit's `warn()` writes to stderr — [plugin_models.py:286-288](src/partcad/wrappers/plugin_models.py#L286).

**Remote daemon / container sandbox**
- Today the daemon is local: an AF_UNIX socket / Windows named pipe, falling back to a one-shot stdio service —
  [src/partcad_client/client.py:708-729](src/partcad_client/client.py#L708). A remote daemon is anticipated ("they will
  not [coincide] once a daemon can be remote") — [src/partcad_cli/AGENTS.md:192-201](src/partcad_cli/AGENTS.md#L192).
- The optional HTTP JSON-RPC transport has "no authentication yet (by design, for now)" and sends every event to
  every subscriber — [src/partcad_service_json_rpc/transport/http.py:10, 24-30, 81](src/partcad_service_json_rpc/transport/http.py#L10).
- `remote` sandbox: forwarded commands go through `RuntimeJsonRpcClient(host, port, token=lease.token)` with no
  `scheme` argument, whose default is `"http"` — [src/partcad/remote_sandbox.py:384-386](src/partcad/remote_sandbox.py#L384); [src/partcad_utils/json_rpc_client.py:147-174](src/partcad_utils/json_rpc_client.py#L147). The remote-docker service refuses non-loopback addresses without a shared bearer token (`remoteSandboxToken`) — [user_config.py:1253-1275](src/partcad_utils/user_config.py#L1253).
- Docker sandbox does not carry the host environment into the container, so env-var credentials do not reach a
  plugin there; the repository parameter does — [partcad-repo-grabcad README:135-138](https://github.com/partcad/partcad-repo-grabcad/blob/55f8e38bf39b005dd8ffef6e8b6556adb463d48f/README.md#L135).

**Logging, caching, cache keys, telemetry, redaction**
- Credentials are "never written into anything this answers: PartCAD caches the answers, and a cache can be shared" —
  [plugin_models.py:568-575](src/partcad/wrappers/plugin_models.py#L568).
- The toolkit's HTTP cache key includes a sha256 (first 16 hex) of the `Authorization`/`Cookie` headers sent, "never
  the credentials", so two accounts on one machine get separate cache entries — [plugin_models.py:347-348, 472-495](src/partcad/wrappers/plugin_models.py#L472). A 401/403 is never negatively cached — [plugin_models.py:505-512](src/partcad/wrappers/plugin_models.py#L505).
- Cross-host redirects strip `Authorization` and `Cookie` (CDN download links) — [plugin_models.py:351-366](src/partcad/wrappers/plugin_models.py#L351).
- PartCAD's own repository-answer cache key hashes the user's overrides of the plugin's parameters (credentials
  included), "Hashed with the rest, so no credential is written anywhere by it" — [src/partcad/project_external_repository.py:658-704](src/partcad/project_external_repository.py#L658); "Every cache keyed on an object's parameters keys on the package's value" — [docs/source/config_objects.rst:886-888](docs/source/config_objects.rst#L886).
- Redaction rules: `SECRET_OPTIONS = ("remote_sandbox_token",)`, `PERSONAL_OPTIONS = ("location",)`, the `user`
  section reported by field only, `git.auth` passwords scrubbed, `PC_*` env vars with TOKEN/KEY/SECRET/PASSWORD/
  CREDENTIAL/AUTH scrubbed — [src/partcad_utils/config_report.py:27-128, 177-187](src/partcad_utils/config_report.py#L27).
  `option_value()` returns any other option unchanged — [config_report.py:120-128](src/partcad_utils/config_report.py#L120).
- `pc config`, `pc system status config` and the daemon's `daemon.status.config` all print
  `"%s: %s" % (key, value)` for every `resolved_options(user_config)` — [src/partcad_cli/click/commands/config.py:21-22](src/partcad_cli/click/commands/config.py#L21); [system/status/config.py:41-42](src/partcad_cli/click/commands/system/status/config.py#L41); [operations.py:2496-2506](src/partcad_service_json_rpc/core/operations.py#L2496) (whose docstring promises "Secrets are taken out here, on the daemon").
  `user_config.parameter_config` is a plain instance attribute (`ParametersConfig`) — [user_config.py:1441-1445](src/partcad_utils/user_config.py#L1441) — whose `__repr__` is the whole section — [user_config.py:36-74](src/partcad_utils/user_config.py#L36).
  (Simulated, not run: a stand-in `dict` subclass with that `__repr__` formats as `parameter_config: ParametersConfig({'//pub/x:svc': {'token': 'SECRET'}})`.)
  `tests/partcad_utils/test_config_report.py` has no case for `parameters` (grep found none).
- The MCP `execute` tool lists `daemon.status.config` as context-free and does not refuse it — [server.py:54-79](src/partcad_client/mcp_server/server.py#L54).
- Telemetry spans record only scalar positional/keyword args of instrumented methods — [src/partcad_utils/telemetry.py:240-266](src/partcad_utils/telemetry.py#L240); requests are dicts.

### Inferences
- The credential crosses process/machine boundaries on every command, not just at login: client config file →
  `context.create.userConfig` (JSON-RPC) → daemon memory (kept verbatim as a fingerprint) → plugin stdin. With today's
  local daemon this is local IPC; with the anticipated remote daemon over the existing HTTP transport it would be
  plaintext, unauthenticated, and the client's *entire* `parameters:` (every plugin's secrets) plus the `user` PII would
  travel with every command — regardless of which plugin the command needs.
- With the `remote` sandbox, a plugin request carrying `request["parameters"]` (and, for a manufacturer, the `user`
  addresses) goes to the container's JSON-RPC endpoint over `http` unless something sets `https`; off-loopback that is
  cleartext on the network apart from the bearer token gate.
- **Probable leak**: `pc config`, `pc system status config`, `pc daemon status config` (and an MCP agent via `execute
  daemon.status.config`) print every saved plugin credential, because `parameter_config` is neither in
  `SECRET_OPTIONS` nor handled like `pii_config`/`git_auth`. These outputs are explicitly "what people paste into bug
  reports and screen recordings" ([config_report.py:30-32](src/partcad_utils/config_report.py#L30)). Needs a one-line
  runtime confirmation.
- A manufacturer plugin's credential parameter must be *declared* in its `partcad.yaml` (with a `default`, e.g. `""`,
  as DigiKey does — [partcad-svc-commerce-digikey partcad.yaml:66-82](https://github.com/partcad/partcad-svc-commerce-digikey/blob/9a799b1b82339668e0978c3ab72aeb0f19955fae/partcad.yaml#L66)), or the saved override never reaches `request["parameters"]`.
- The `--set` path puts secrets on the command line (shell history, `ps`); the MCP path puts them in the agent's
  transcript; the manual page's `GET` form puts them in the URL of a request to 127.0.0.1, which (when the manual page
  is opened in the user's everyday browser because no extension-capable browser was found) would land in that
  browser's history. None of these is mitigated in code that I found.

### Gaps
- Not verified at runtime (no `.venv`): the `pc config` / status-config credential exposure.
- Did not check whether `pc info <package>` or other inspection commands print a provider's/repository's resolved
  `parameters` (where the override has become `default`); `info_object` handles parts/assemblies/etc. only
  ([operations.py:1331-1432](src/partcad_service_json_rpc/core/operations.py#L1331)).
- Whether the docker (mount-mode) sandbox makes the host `~/.cache` (where plugins cache derived tokens) visible was
  not traced.

## 2. Expiry and refresh: write-back, `--check`, and a session that dies mid-use

### Takeaway
There is **no mechanism** for a plugin to write a refreshed credential back after a normal `get`/`quote`/`avail` call:
only `login` returns parameters, and only the client's `pc login` / MCP `login` write them. Plugins that need a
short-lived derived token cache it themselves in their own cache directory (OAuth2 client-credentials access tokens,
McMaster-Carr's 23-hour `AuthToken`), which works only because the long-lived secret never changes. An expired cookie
or token surfaces as a 401/403 → "run `pc login` again"; the persistent PartCAD browser profile is the de-facto refresh
(the site's own web session renews the cookie in that profile, and the next `pc login` re-captures it).

### Cited Findings
- Only two callers of `save_parameter_overrides` exist — `pc login` and the MCP `login` tool (plus the MCP in-memory
  patch); a grep of `src/` found no other writer, and no `refresh_token` handling anywhere in `src/`, `incubator/` or
  `docs/source` — [login.py:162](src/partcad_cli/click/commands/login.py#L162); [server.py:797-801](src/partcad_client/mcp_server/server.py#L797).
- `Plugin.login`'s answer shapes are `{"parameters", "message"}`, `{"browser"}`, `{"instructions"}` only — [src/partcad/plugin.py:105-157](src/partcad/plugin.py#L105). Other apis return `output` that PartCAD reads as data (e.g. quote: `price`, `currency`, `cartId`) — [docs/source/config_making.rst:1528-1535](docs/source/config_making.rst#L1528).
- The daemon re-reads nothing on its own; instead it polls `~/.partcad/config.yaml` every second, compares a sha256 of
  its *content*, and **leaves** (restarts) on any change — [src/partcad_service_json_rpc/config_restart.py:6-21, 75, 82-91](src/partcad_service_json_rpc/config_restart.py#L6).
- A changed `userConfig` copy rebuilds the warm context — [operations.py:2843-2850](src/partcad_service_json_rpc/core/operations.py#L2843); a changed override changes every repository cache key — [project_external_repository.py:669-677](src/partcad/project_external_repository.py#L669).
- Derived-token caching pattern (OAuth2 client credentials): `bearer()` keeps `{"token", "expires"}` at
  `<cache>/tokens/<sha256(token_url, client_id, client_secret)>`, mode 0600, reused while > 60 s remain, re-fetched on
  miss; "asked again next time" if the cache cannot be written — [incubator/_shared/distributor.py:937-988](incubator/_shared/distributor.py#L937). Cache root is `$PARTCAD_<SITE>_CACHE` or `$XDG_CACHE_HOME/partcad-<site>` — [plugin_models.py:301-308](src/partcad/wrappers/plugin_models.py#L301).
- McMaster-Carr: `POST /v1/login` with username/password over the client-certificate TLS context → `AuthToken`, cached
  23 h at 0600; on a 403 it retries once with `fresh=True` ("An expired token is a 403 like any refusal") — [mcmaster.py:226-276](https://github.com/partcad/partcad-svc-commerce-mscmaster-carr/blob/504168f830742f8044ace45824ad8ca00fe8f427/mcmaster.py#L226).
- Short-lived cookie tokens and no refresh: Printables' `auth.access_token` "the website renews as it is used and …
  lasts minutes rather than days; `pc login` says when the one it saved expires. When a paid model's download says
  Printables did not take the token, run `pc login` again" — [partcad-repo-printables README:146-149](https://github.com/partcad/partcad-repo-printables/blob/58312596b18ea94ada92af19dd5a664a8a3dc3a2/README.md#L146); `whoami` reports the JWT's `exp` — [printables_repo.py:123-130, 279-300](https://github.com/partcad/partcad-repo-printables/blob/58312596b18ea94ada92af19dd5a664a8a3dc3a2/printables_repo.py#L279).
  GrabCAD: "A session lasts as long as GrabCAD keeps it: when downloads start to say the sign-in is wanted again, copy a
  new one" — [partcad-repo-grabcad README:130-132](https://github.com/partcad/partcad-repo-grabcad/blob/55f8e38bf39b005dd8ffef6e8b6556adb463d48f/README.md#L130).
  MakerWorld on refusal: "was not accepted; it may have expired" — [makerworld_repo.py:256-257](https://github.com/partcad/partcad-repo-makerworld/blob/a6ebed23c2f7b5d2353ac4878d3d01de1cfa4b59/makerworld_repo.py#L256).
- Mid-use expiry path in the toolkit: 401/403 → `NeedsCredentials("…the site wants a sign-in, or did not accept the
  one given")` — [plugin_models.py:404-428](src/partcad/wrappers/plugin_models.py#L404); a repository's `serve()` turns
  it into a stderr warning and `None` — [plugin_models.py:1140-1153](src/partcad/wrappers/plugin_models.py#L1140); a
  store's `quote`/`avail` re-raise as `RuntimeError` (the command fails with the reason) — [distributor.py:1042-1049](incubator/_shared/distributor.py#L1042).
- An in-run-only cookie refresh exists in one store: Home Depot keeps an anonymous cookie jar in module globals and
  "Refresh[es] cookies after each request to avoid bot detection"; nothing is persisted — [homedepot.py:66-81](https://github.com/partcad/svc-commerce-homedepot/blob/548d25cea7f0e867f93bdbcbb02e3b4aeb737daa/homedepot.py#L66).
- `pc login --check`: no browser is chosen (`chosen` only when `interactive and not manual and not check`) — [login.py:119-121](src/partcad_cli/click/commands/login.py#L119);
  the plugin's `open_browser` raises `CheckOnly` ("logging in needs the browser … and this is only a check") — [plugin_login.py:298-301](src/partcad/wrappers/plugin_login.py#L298);
  `Site.login` returns "Already logged in to X as Y" when `whoami` accepts current credentials — [plugin_models.py:1066-1072](src/partcad/wrappers/plugin_models.py#L1066);
  nothing is saved under `--check` — [login.py:159](src/partcad_cli/click/commands/login.py#L159); the option help says "Exits non-zero if they do not work" — [login.py:39-43](src/partcad_cli/click/commands/login.py#L39).
- `whoami` contract: return a name, or `None` when the site refuses; raise `SiteError` when the site could not be asked
  ("which is not the same as being told no") — [plugin_models.py:1022-1028](src/partcad/wrappers/plugin_models.py#L1022); `Http.probe` treats 401/403 as an answer and a bot check / no answer as an error — [plugin_models.py:518-535](src/partcad/wrappers/plugin_models.py#L518). If the fresh capture cannot be checked, it is saved anyway with a message — [plugin_models.py:1080-1090](src/partcad/wrappers/plugin_models.py#L1080).

### Inferences
- `CheckOnly` is an ordinary `Exception` (unlike `BrowserNeeded`), so `--check` failing works by the exception escaping
  the plugin → `{"exception"}` → `RuntimeError("logging in failed")` → `status: failed` → `ClickException` (exit 1).
  A plugin with a blanket `except Exception` around `open_browser` would mask a failed check.
- A per-call write-back of rotating credentials through `config.yaml` would, as the code stands, restart a running
  daemon on every rotation (content-hash watcher), rebuild warm contexts (fingerprint), and invalidate every
  repository/shape cache key that hashes the plugin's overrides. So rotating values (OAuth2 refresh tokens that rotate
  on use, renewed session cookies) do not belong in `parameters:` even if a write-back path were added; the
  distributor pattern — long-lived secret in `parameters`, short-lived derived token in the plugin's own 0600 cache —
  is the one that fits today. OAuth2 *authorization-code + refresh-token* flows, where the refresh token itself rotates,
  cannot be supported durably without a new mechanism.
- Derived-token caches live where the plugin runs (the sandbox's `$HOME/.cache` or `$XDG_CACHE_HOME`); in a container
  sandbox with an ephemeral or read-only home the token is simply re-fetched each run (the code tolerates failure to
  write), costing a token request per command.
- For cookie-based logins the effective refresh is "run `pc login` again"; because the PartCAD profile persists, a site
  whose own web session silently renews will often re-capture without user interaction — but only on the client
  machine, and only when a person (or agent) runs `pc login`.

### Gaps
- No live measurement of any site's token/cookie lifetime was possible here (Printables' "minutes" is quoted by the
  README as "the third party's word" — [README:288-289](https://github.com/partcad/partcad-repo-printables/blob/58312596b18ea94ada92af19dd5a664a8a3dc3a2/README.md#L288)).
- Not checked: whether `pc login` re-saving unchanged parameters produces byte-identical YAML (if not, even an
  "Already logged in" re-run would restart the daemon).

## 3. Which existing plugins log in, with what credential, how they verify and instruct

### Takeaway
Six model-site repository plugins in the index (`//pub/collection/*`, all on `plugin_models`), Google Earth (graduated
from the incubator, not in the index) and four graduated-but-unindexed distributor packages implement `login`; between them they cover every credential kind except "OAuth2 user token with
refresh": session cookie (GrabCAD), cookie-held JWT access token (Printables/Prusa Account, MakerWorld/Bambu Lab),
API key/token pasted by hand (Thingiverse App Token, Sketchfab, Cults3D nick+key, Mouser, Google Maps), OAuth2
implicit-grant token via redirect capture (Thingiverse/Sketchfab, only with the user's own registered app), OAuth2
client credentials (DigiKey, Octopart/Nexar), and username+password+client certificate (McMaster-Carr). Store plugins
in the index (Home Depot, Lowe's, goBILDA, LEGO, IKEA) have no login; BrickLink needs OAuth 1.0a values set by hand.

### Cited Findings
Index placement: model sites are `//pub/collection/<site>:<site>_repo`, "the name that `pc login` and the
`parameters` of ~/.partcad/config.yaml use", requiring PartCAD ≥ 0.9.20 — `collection/partcad.yaml:11-18` in the index
(both branches). Stores are under `svc/commerce` (gobilda, homedepot, lowes, lego-pick-a-brick, bricklink, ikea). The
four distributors and Google Earth are **not** registered in the index (grep of every `partcad.yaml` on both branches
found no digikey/octopart/mouser/mcmaster/google-earth). Note: PartCAD docs still use `//pub/universe/grabcad:grabcad_repo`
— [docs/source/plugins/login.rst:15](docs/source/plugins/login.rst#L15), [docs/source/cli.rst:279-280](docs/source/cli.rst#L279) — which does not match the index.

| Plugin (index path or repo) | Credential kind (`CREDENTIALS`) | Capture in `login_spec` | `whoami` | Notes |
|---|---|---|---|---|
| GrabCAD `//pub/collection/grabcad:grabcad_repo` | **web session cookie** `_grabcad_session` → `session` (`GRABCAD_SESSION`) | `cookie` on grabcad.com, `done_when.fetch` `/community/api/v1/members/me` = 200 (every visitor has a session cookie) | `GET members/me` with `Cookie:`; 204/401/403 → not logged in | "GrabCAD has no public API … GrabCAD has no API keys"; accepts the cookie value or a whole pasted `Cookie` header — [grabcad_repo.py:16-20, 73-139](https://github.com/partcad/partcad-repo-grabcad/blob/55f8e38bf39b005dd8ffef6e8b6556adb463d48f/grabcad_repo.py#L73) |
| Printables `…/printables:printables_repo` | **cookie-held JWT** `auth.access_token` (Prusa Account) → `token` (`PRINTABLES_TOKEN`), sent as `Authorization: Bearer` | `cookie` + `match` JWT regex, `done_when.fetch` GraphQL `{me{id}}`; guide through account.prusa3d.com | GraphQL `me`; reports JWT expiry | Only paid models need it; token sent only with a paid download's link request — [printables_repo.py:94-154, 279-320](https://github.com/partcad/partcad-repo-printables/blob/58312596b18ea94ada92af19dd5a664a8a3dc3a2/printables_repo.py#L148); [README:146-155](https://github.com/partcad/partcad-repo-printables/blob/58312596b18ea94ada92af19dd5a664a8a3dc3a2/README.md#L146) |
| MakerWorld `…/makerworld:makerworld_repo` | **cookie-held JWT** `token` (Bambu Lab account) → `token` (`MAKERWORLD_TOKEN`), `Authorization: Bearer` | `cookie` on makerworld.com + JWT `match`; guide to "Log in" button and bambulab.com | `GET https://api.bambulab.com/v1/user-service/my/profile` | Previews need no login — [makerworld_repo.py:126-195](https://github.com/partcad/partcad-repo-makerworld/blob/a6ebed23c2f7b5d2353ac4878d3d01de1cfa4b59/makerworld_repo.py#L126) |
| Thingiverse `…/thingiverse:thingiverse_repo` | **API token** (App Token) → `token` (`THINGIVERSE_TOKEN`) | default: `ask` (secret, `match ^[A-Za-z0-9_-]{16,}$`) on `/apps/create`; with user's own `client_id`+`redirect_uri` parameters and interactive: **OAuth implicit grant**, `redirect` capture of `access_token` | `GET /users/me` Bearer | "PartCAD registers no app with Thingiverse" — [thingiverse_repo.py:61-140](https://github.com/partcad/partcad-repo-thingiverse/blob/89cf663e3775c8ba31d00ea57ecaa62d88feed16/thingiverse_repo.py#L61) |
| Sketchfab `…/sketchfab:sketchfab_repo` | **API token** `token` (`Authorization: Token`) or **OAuth implicit** `oauth_token` (Bearer) | `ask` on `/settings/password`, or `redirect` with user's own app | (at :224) | [sketchfab_repo.py:176-294](https://github.com/partcad/partcad-repo-sketchfab/blob/e630a4fc9c6b7480d2df32a5925c561726f10ec2/sketchfab_repo.py#L176) |
| Cults3D `…/cults3d:cults3d_repo` | **nick + API key** (HTTP Basic) `nick`,`api_key` | two `ask`s with `match`; guide on `/api/keys` ("a read-only one is enough") | (at :305) | Key page markup unreadable "the site shows anything that is not a browser a bot check", so values are pasted — [cults3d_repo.py:156-176, 324-361](https://github.com/partcad/partcad-repo-cults3d/blob/cde2e273e65f1febe49ce32834044eb120892c4d/cults3d_repo.py#L156) |
| Google Earth (`partcad-repo-google-earth`, not in index; own `login`, not `plugin_models.Site`) | **Google Maps Platform API key** `api_key` (`GOOGLE_MAPS_API_KEY`) | `ask` with `match ^AIza…{35}$`, guide through Cloud console enabling 3 APIs, timeout 1800 | `diagnose()` asks each API one cheap question and classifies errors (invalid/disabled/restricted/billing) | package `"persist": false` — [google_earth_repo.py:105-112, 294, 342-500](https://github.com/partcad/partcad-repo-google-earth/blob/7655b5a6c7854f82fad6efb40fe8b9058094ccbf/google_earth_repo.py#L455) |
| DigiKey (`partcad-svc-commerce-digikey`: store `digikey` + catalogue `digikey_repo`) | **OAuth2 client credentials** `client_id`,`client_secret` | two `ask`s on developer.digikey.com | fetches a token via `bearer()` | Store and catalogue each log in separately — [digikey.py:148-160, 383-402](https://github.com/partcad/partcad-svc-commerce-digikey/blob/9a799b1b82339668e0978c3ab72aeb0f19955fae/digikey.py#L148); declared params [partcad.yaml:57-82](https://github.com/partcad/partcad-svc-commerce-digikey/blob/9a799b1b82339668e0978c3ab72aeb0f19955fae/partcad.yaml#L57) |
| Octopart/Nexar | **OAuth2 client credentials** (Basic auth, scope `supply.domain`) | `ask` for id; `dom` capture of the secret from `input[disabled]` on the app's authorization page | `bearer()` | [octopart.py:136-143, 345-392](https://github.com/partcad/partcad-svc-commerce-octopart/blob/13d1d8d45c835a5e24fa9f2c52a8d3541cf88367/octopart.py#L345) |
| Mouser | **API key** `api_key` | `ask` | one real search ("One request of the day's thousand") | [mouser.py:83-88, 200-222](https://github.com/partcad/partcad-svc-commerce-mouser/blob/006598568fe74bc44775931f2e33b3b8b47f4185/mouser.py#L200) |
| McMaster-Carr (`partcad-svc-commerce-mscmaster-carr`) | **username + password + client certificate + cert password** | four `ask`s (certificate = "The path of the client certificate") | real `POST /v1/login` with the cert | §below — [mcmaster.py:184-197, 382-407](https://github.com/partcad/partcad-svc-commerce-mscmaster-carr/blob/504168f830742f8044ace45824ad8ca00fe8f427/mcmaster.py#L184) |
| BrickLink store (`svc-commerce-bricklink`) | **OAuth 1.0a** consumerKey/Secret + tokenValue/Secret, HMAC-SHA1 | no `login`: set in config or `BRICKLINK_*` env | — | "A token is issued for the IP addresses it was registered for; register 0.0.0.0 to use it from anywhere" — [bricklink.py:59-73, 338-369, 404-406](https://github.com/partcad/svc-commerce-bricklink/blob/99010beddfd02fa98ad179bc86c315f1afb033d9/bricklink.py#L404) |

- `Site.login` (shared by all `plugin_models` sites): read current creds → if any and `whoami` accepts, keep → else
  `open_browser(**login_spec(), instructions=login_instructions())` → `credentials_from(captured)` → `whoami(fresh)` →
  save or `LoginFailed` — [plugin_models.py:1054-1093](src/partcad/wrappers/plugin_models.py#L1054). Agent instructions
  are `LOGIN_INSTRUCTIONS` plus an auto-generated sentence naming the env vars and config parameters — [plugin_models.py:1038-1052](src/partcad/wrappers/plugin_models.py#L1038).
- Distributor toolkit (`incubator/_shared/distributor.py`, copied into each package by digest) wraps `pm.login` and
  appends "The store and the catalogue keep their keys apart: log in to both" — [distributor.py:45-49, 921-935, 1028-1041](incubator/_shared/distributor.py#L921); the incubator README lists this double login as something PartCAD "could do better", suggesting a package-level credential — [incubator/README.md:122-125](incubator/README.md#L122) (since addressed by `shared: true`, §1, though no cloned package uses `shared: true` yet: grep of every `partcad.yaml` found none).
- **McMaster-Carr's client certificate**: the `certificate` parameter is "the path of the .pfx/.p12 (or .pem) file, or
  its content in base64 where the plugin runs in a container that cannot see the file" — [mcmaster.py:190-197](https://github.com/partcad/partcad-svc-commerce-mscmaster-carr/blob/504168f830742f8044ace45824ad8ca00fe8f427/mcmaster.py#L190).
  `certificate_context()` reads the path *where the plugin runs* if it exists, else base64-decodes; PKCS#12 is
  converted with `cryptography` to an unencrypted PEM written to a `mkstemp` file only long enough for
  `ssl.load_cert_chain`, then unlinked — [mcmaster.py:117-163](https://github.com/partcad/partcad-svc-commerce-mscmaster-carr/blob/504168f830742f8044ace45824ad8ca00fe8f427/mcmaster.py#L117).
  The derived-token cache key hashes `base\nusername\npassword\ncertificate` — [mcmaster.py:226-236](https://github.com/partcad/partcad-svc-commerce-mscmaster-carr/blob/504168f830742f8044ace45824ad8ca00fe8f427/mcmaster.py#L226). A mock server over TLS with a client certificate was used for end-to-end tests — [incubator/README.md:104-112](incubator/README.md#L104).

### Inferences
- The MakerWorld credential is a Bambu Lab cloud account bearer token (its `whoami` is answered by
  `api.bambulab.com`'s user service). That is the same account family as Bambu printers' cloud — so a 3D-printing
  manufacturer plugin reusing it would hold a token whose scope PartCAD cannot limit. (What else that token can do was
  not verified.)
- The McMaster pattern generalises to any "file" credential: since parameters must be scalars and a container sandbox
  may not see the client's filesystem, a file has to travel as base64 inside `config.yaml` (and therefore inside every
  `context.create`), or as a path valid on the *daemon/sandbox* machine — not on the client where `pc login` ran.
  `request_paths.carry` (CLAUDE.md) does not apply to plugin parameters.
- "Account password stored in plaintext" already happens (McMaster `password`, cert password) — the 0600 file is the
  only protection.

### Gaps
- Did not read every plugin's README on credentials; READMEs for Thingiverse/Sketchfab/Cults3D/distributors were only
  sampled via their code.
- No plugin in these repos handles 2FA explicitly (it happens in the browser, if at all); not confirmed per site.

## 4. API key vs. web-session cookie as a PartCAD credential

### Takeaway
The plumbing treats both identically once captured — a string in `parameters:`, plaintext in a 0600 file, shipped
with every command, sent by the plugin as a header — so the differences are all in obtaining, lifetime, scope and
risk. An API key (or OAuth client credentials) is obtained once by the user on the site's developer page (`ask`/`dom`
capture or `--set`), is long-lived, revocable and often scopable; a session cookie is captured invisibly from PartCAD's
own browser profile, expires on the site's schedule with no refresh path in PartCAD, carries the whole web account,
and depends on the site tolerating a non-browser client — which this codebase deliberately does not fake.

### Cited Findings
- Obtaining: cookies come from the browser's cookie API (HttpOnly included), read "fresh on every check rather than
  remembered" — [browsers/README.md:64-65](browsers/README.md#L64); keys are pasted into the extension banner (`ask`) or
  read off a page (`dom`) — [login.rst:86-92](docs/source/plugins/login.rst#L86). Every site whose credential is a
  cookie needs a `match` or a `done_when.fetch`, "so that what a visitor has is never taken for what a signed-in user
  has" — [login.rst:94-97](docs/source/plugins/login.rst#L94); GrabCAD: "Every visitor has a session cookie, signed in
  or not, so the cookie alone says nothing" — [grabcad_repo.py:115-123](https://github.com/partcad/partcad-repo-grabcad/blob/55f8e38bf39b005dd8ffef6e8b6556adb463d48f/grabcad_repo.py#L115). `done_when.fetch` does not follow redirects, "so a login page's 200 behind a 302 is not taken for 'signed in'" — [browsers/README.md:72-76](browsers/README.md#L72).
- Agent/headless path: a cookie must be fished out of developer tools by a person ("the browser's developer tools show
  it, under Application (or Storage) > Cookies") — [grabcad_repo.py:73-77](https://github.com/partcad/partcad-repo-grabcad/blob/55f8e38bf39b005dd8ffef6e8b6556adb463d48f/grabcad_repo.py#L73), [printables_repo.py:148-153](https://github.com/partcad/partcad-repo-printables/blob/58312596b18ea94ada92af19dd5a664a8a3dc3a2/printables_repo.py#L148); with nobody at the screen Thingiverse/Sketchfab fall back from OAuth to the hand-copyable token because "an OAuth grant's lives in the address of a page that never loads" — [thingiverse_repo.py:96-99](https://github.com/partcad/partcad-repo-thingiverse/blob/89cf663e3775c8ba31d00ea57ecaa62d88feed16/thingiverse_repo.py#L96).
- Storing: identical for both — `parameters:` in `~/.partcad/config.yaml`, 0600 (§1).
- Using: plugins send keys/tokens as `Authorization` (Bearer, Token, Basic) and GrabCAD's session as `Cookie:`;
  the toolkit strips both on cross-host redirects and keys its cache on their digest (§1). Plugins identify
  themselves: User-Agent `Mozilla/5.0 (compatible; PartCAD-<site>/<v>; +<homepage>)` — [plugin_models.py:678-686](src/partcad/wrappers/plugin_models.py#L678);
  "These plugins identify themselves and do not pretend to be a browser, so a site that admits only browsers turns
  them away. That is reported as what it is, with nothing tried to get past it" (AWS WAF, Cloudflare, CloudFront
  detection) — [plugin_models.py:324-345, 437-441](src/partcad/wrappers/plugin_models.py#L324).
- Lifetime/refresh evidence: Printables cookie-JWT lasts "minutes rather than days" and is renewed by the website as
  used (§2); GrabCAD "as long as GrabCAD keeps it" (§2); API keys last until deleted ("the key may have been deleted:
  run `pc login`") — [cults3d_repo.py:192-196](https://github.com/partcad/partcad-repo-cults3d/blob/cde2e273e65f1febe49ce32834044eb120892c4d/cults3d_repo.py#L192); client-credentials access tokens are derived and cached until `expires_in` (§2).
- Scope evidence: Cults3D "a read-only one is enough"; Octopart scope `supply.domain` chosen at app creation ("a scope
  cannot be added afterwards"); Google key "restrict it to those three APIs" — [cults3d_repo.py:156-160](https://github.com/partcad/partcad-repo-cults3d/blob/cde2e273e65f1febe49ce32834044eb120892c4d/cults3d_repo.py#L156), [octopart.py:137-143](https://github.com/partcad/partcad-svc-commerce-octopart/blob/13d1d8d45c835a5e24fa9f2c52a8d3541cf88367/octopart.py#L137), [google_earth_repo.py:74-80](https://github.com/partcad/partcad-repo-google-earth/blob/7655b5a6c7854f82fad6efb40fe8b9058094ccbf/google_earth_repo.py#L74). Cookies carry no scope in any plugin.
- Least-use practice in an existing cookie plugin: Printables sends the token "with the request for a paid model's
  file's download link and nothing else", partly because an expired token makes the API refuse even requests that
  need none — [printables README:150-157](https://github.com/partcad/partcad-repo-printables/blob/58312596b18ea94ada92af19dd5a664a8a3dc3a2/README.md#L150); GrabCAD: "The cookie is sent to grabcad.com, and to nothing else" — [grabcad README:131-132](https://github.com/partcad/partcad-repo-grabcad/blob/55f8e38bf39b005dd8ffef6e8b6556adb463d48f/README.md#L131).
- Network binding: BrickLink tokens are bound to registered IPs — [bricklink.py:404-406](https://github.com/partcad/svc-commerce-bricklink/blob/99010beddfd02fa98ad179bc86c315f1afb033d9/bricklink.py#L404).
- Design-level risk limits already in place: PartCAD-only browser profile, extension present only there, refuses
  incognito ([browser.py:21-28](src/partcad_client/browser.py#L21); [browsers/README.md:119-120](browsers/README.md#L119));
  consent page before any capture ([login.rst:165-172](docs/source/plugins/login.rst#L165)); origin-limited capture and
  loopback-only, nonce-scoped delivery ([browsers/README.md:104-111](browsers/README.md#L104); [src/partcad_client/login.py:63-69](src/partcad_client/login.py#L63)); `match` patterns; never touching or capturing bot-check grants ([login.rst:174-177](docs/source/plugins/login.rst#L174)); the extension's `<all_urls>` power justified and bounded by those rules ([browsers/README.md:124-134](browsers/README.md#L124)); Firefox build declares `authenticationInfo` data collection ([browsers/README.md:134-136](browsers/README.md#L134)).
- ToS: plugins point users to the site's terms (e.g. "GrabCAD's terms of use are at https://grabcad.com/terms") —
  [grabcad README:279-280](https://github.com/partcad/partcad-repo-grabcad/blob/55f8e38bf39b005dd8ffef6e8b6556adb463d48f/README.md#L279), [makerworld README:294-295](https://github.com/partcad/partcad-repo-makerworld/blob/a6ebed23c2f7b5d2353ac4878d3d01de1cfa4b59/README.md#L294); no code-level ToS check exists.

### Inferences
- **Session cookie = full account access.** GrabCAD's `_grabcad_session` and the Bambu/Prusa account JWTs are the
  same credential the website itself uses; for a print bureau that would include saved payment methods, order
  placement, address book and order history. PartCAD stores it in a plaintext file, ships it with every command
  (§1), and (probably) prints it in `pc config` (§1) — a materially worse blast radius than a scoped, revocable API key.
- **CSRF / state-changing requests**: every existing cookie plugin only *reads* (GET details, GET/POST GraphQL queries,
  download links). A manufacturer plugin that creates a quote/cart via a site's web endpoints with a session cookie
  would usually also need the site's CSRF token (often in a cookie+header pair or a page meta tag) — capturable with
  a second `cookie`/`dom` capture, but nothing in `plugin_models` handles it, and such tokens often rotate per session.
- **Bot protection** favours API keys: cookie-based web endpoints of consumer sites sit behind Cloudflare/WAF
  (Printables and MakerWorld showed "Verify you are human" in the browser during testing — [printables README:291-297](https://github.com/partcad/partcad-repo-printables/blob/58312596b18ea94ada92af19dd5a664a8a3dc3a2/README.md#L291), [makerworld README:249-255](https://github.com/partcad/partcad-repo-makerworld/blob/a6ebed23c2f7b5d2353ac4878d3d01de1cfa4b59/README.md#L249)), and since PartCAD never carries the challenge's clearance into the plugin and does not spoof a browser, a cookie captured after passing a challenge may still be refused when replayed from the plugin's own HTTP client — reported as `Refused`, not worked around.
- **IP/device binding**: a cookie captured on the client is replayed from wherever the sandbox runs; with a remote
  daemon/sandbox that is another IP, which sites that bind sessions (as BrickLink binds tokens) may reject.
- **2FA** is naturally handled by the browser flow (the person signs in), but means an unattended re-login is
  impossible once a cookie expires — another reason short-lived cookies fit agent/CI use badly.
- **Revocation**: an API key can be deleted on the developer page without touching the user's web session; a
  captured session cookie is revoked only by logging out that session (or all sessions) on the site.
- **ToS**: using a captured session cookie against a site's private web endpoints from a non-browser client is the
  usage most likely to conflict with a site's terms; the codebase's posture (honest UA, no bot-check evasion, consent
  page) limits but does not settle that.

### Gaps
- No site's actual ToS wording on automated use of session cookies was checked here (out of scope: code-only research).
- Whether any 3D-printing service binds sessions to IP/UA was not checked.

## 5. The order flow, what `quote` sends, and payment

### Takeaway
Ordering is unimplemented end to end: `ProviderRequestOrder.__init__` raises `NotImplementedError`, `pc supply order`
is an empty body, no JSON-RPC method orders, and the docs say an `order` api "does not need to be implemented as there
is no infrastructure for payments yet". A manufacturer's `quote` receives the cart with each part's geometry (binary +
format), print data for printed parts, its declared parameters (credentials), coarse `userInfo`, and — manufacturer
only — the whole `user` PII section (names, email, phone, company, shipping and billing addresses), and answers
`price`, `currency`, `cartId`. Nothing about payment exists.

### Cited Findings
- `ProviderRequestOrder.__init__` → `raise NotImplementedError("Order request is not implemented yet.")` — [src/partcad/plugin_request_provider_order.py:14-20](src/partcad/plugin_request_provider_order.py#L14).
- `pc supply order` body is TODOs and `pass` — [src/partcad_cli/click/commands/supply/order.py:14-25](src/partcad_cli/click/commands/supply/order.py#L14); the factory has a `query_order` that would call the script's `order` api — [src/partcad/plugin_factory_provider_manufacturer.py:150-155](src/partcad/plugin_factory_provider_manufacturer.py#L150); no `order` entry in [rpc/methods.py](src/partcad_service_json_rpc/rpc/methods.py) (grep found none).
- Docs: `order` takes `request["cartId"]`; "Order API does not need to be implemented as there is no infrastructure for
  payments yet" — [docs/source/config_making.rst:1491-1497, 1537-1542](docs/source/config_making.rst#L1537). The
  distributors refuse it: "ordering is not implemented: put the quote's lines in a cart at <site>" — [distributor.py:1052-1056](incubator/_shared/distributor.py#L1052).
- Manufacturer `quote` input/output: `cart.parts[id].format`, `.binary`, `request["user"]`, output `price`,
  `currency`, `cartId` — [config_making.rst:1499-1535](docs/source/config_making.rst#L1499). Cart items carry
  `manufacturing` print data (design and process settings) — [src/partcad/plugin_provider_data_cart.py:97-102](src/partcad/plugin_provider_data_cart.py#L97); the geometry sent for a printed part is its design, not the as-printed mesh — [plugin_factory_provider_manufacturer.py:17-47](src/partcad/plugin_factory_provider_manufacturer.py#L17).
- `request["user"] = pii_config.to_dict()` only when the provider's `type == "manufacturer"`; every plugin gets
  `request["userInfo"]` (country, state, city, language, currency — "nothing that identifies them") — [plugin_factory_python.py:209-216](src/partcad/plugin_factory_python.py#L209); [user_config.py:762-795](src/partcad_utils/user_config.py#L762); [config_making.rst:1367-1387](docs/source/config_making.rst#L1367).
- The `user` section's fields (firstName, lastName, email, phone, company, line1/2, countryCode, stateCode, zipCode,
  city) and `shippingAddress`/`billingAddress` overrides — [docs/source/maintenance/telemetry.rst:84-143](docs/source/maintenance/telemetry.rst#L84); `PIIConfig` fills both address blocks from the parent fields — [user_config.py:90-110](src/partcad_utils/user_config.py#L90).
- The example manufacturer (`examples/provider_manufacturer`, a pseudo 3D printer writing G-code) declares only
  geometry/output parameters, no credentials — [examples/provider_manufacturer/partcad.yaml](examples/provider_manufacturer/partcad.yaml).
- Quotes without a currency are taken as USD with a warning — [config_making.rst:1432-1440](docs/source/config_making.rst#L1432); `_as_price` tolerates junk prices — [operations.py:6253-6272](src/partcad_service_json_rpc/core/operations.py#L6253).

### Inferences
- A print-service plugin today can at most quote (and perhaps create a server-side cart/quote id returned as
  `cartId`); the user completes purchase on the site. That also caps the damage of a captured session cookie *through
  PartCAD's own flows* — but not what the plugin script itself could do with it.
- Because the full PII `user` section is sent to every manufacturer plugin on every quote (not only one that needs
  shipping), a print bureau plugin would receive name/email/phone/addresses even for an anonymous price check.

### Gaps
- `supply_quote` in the daemon ([operations.py:5948](src/partcad_service_json_rpc/core/operations.py#L5948)) was not
  read in full; whether quotes are cached, and on what key, was not traced.

## 6. Gaps a per-user-credential manufacturer plugin would hit, and suggestions

### Takeaway
The login machinery is already sufficient for "user pastes an API key / signs in once and a long-lived token is
captured", including headless agent use and shared provider+repository credentials. What it lacks for print bureaus is
(a) any way to persist a rotated/refreshed credential, (b) a notion of a *secret* parameter (redaction, selective
shipping), (c) safe handling of file credentials and remote execution, and (d) the order/payment half.

### Cited Findings
(Each gap is grounded in findings above; the suggestions are my own.)
- No write-back outside `login` (§2) → OAuth2 authorization-code flows with rotating refresh tokens, and cookies that
  the site renews in the browser, cannot be kept fresh.
- Any `config.yaml` change restarts the daemon and rebuilds contexts; overrides key the caches (§2).
- Redaction does not cover `parameters:` (§1, inferred) and there is no `secret` flag on parameter declarations:
  declarations accept `type`, `enum`, `min`, `max`, `default`, `desc`, `shared` — [config_making.rst:1335-1344](docs/source/config_making.rst#L1335); [parameters.py:443-447](src/partcad_utils/parameters.py#L443).
- The whole client `parameters:` section (all plugins' credentials) and the whole `user` section travel with every
  `context.create` (§1).
- Credentials must be scalars (§1); a file is a path on the sandbox machine or base64 (§3, McMaster).
- Env-var credentials do not reach container sandboxes (§1).
- Order/payment unimplemented (§5).
- Overrides apply only to declared parameters (§1).
- The incubator flagged double login for store+catalogue — now addressable with `shared: true` (§1, §3).

### Inferences (suggestions)
1. **Prefer API keys / OAuth client credentials / personal access tokens** for print-bureau plugins; use the
   distributor pattern: long-lived secret in `parameters` (declared with `default: ""`, `shared: true` if a repository
   and a manufacturer of one package share it), short-lived access token cached by the plugin at 0600 in its cache dir
   keyed by a digest of the secret (`distributor.bearer` — [distributor.py:937-988](incubator/_shared/distributor.py#L937)).
2. **If a site only has web sessions**, capture with `cookie` + strict `match` + `done_when.fetch` against a "who am I"
   endpoint, send the cookie only on the requests that need it (Printables' rule), and treat 401/403 as
   `NeedsCredentials` with a "run `pc login`" message; expect short lifetimes and bot checks; do not attempt checkout.
3. **Add a credential store separate from `config.yaml`** (e.g. `~/.partcad/credentials/` or the OS keyring), written
   only by the client, *not* part of the `userConfig` fingerprint, the config watcher, or cache keys; and a
   plugin-side way to return refreshed values (e.g. `output["credentials"]` on any api, carried back in the RPC answer
   and saved by the client, never by the daemon — consistent with "the daemon writes nothing"). For rotating refresh
   tokens this needs a compare-and-swap under the existing file lock to survive concurrent commands.
4. **Mark parameters `secret: true`** in declarations; scrub them (and, pending that, the whole `parameters:` section's
   values) in `config_report.option_value`; never echo them in `pc info`/`inspect`; and send only the parameters of
   the plugin a command actually needs instead of the whole section.
5. **Fix `remote` sandbox transport** to use `https` (or refuse off-loopback http) before credential-bearing requests
   go to it; require auth+TLS before any remote daemon receives `userConfig`.
6. **File credentials** (client certs): read the file on the *client* at `pc login` time and store its base64 (the
   McMaster fallback), so the credential works wherever the sandbox runs.
7. **Minimise PII**: send `request["user"]` to a manufacturer only for `quote`/`order` (not `caps`) and consider an
   opt-in per provider, since an anonymous price check does not need a name and phone.
8. **Secrets on argv / in agent transcripts**: offer `--set NAME=-` reading stdin, and recommend in MCP instructions
   that the user run `pc login` themselves for cookie/password credentials rather than pasting them to the agent.
9. **Order/payment**: design `order` so it never handles card data in PartCAD (redirect the user to the bureau's
   checkout with the `cartId`), which keeps a session cookie's payment powers out of plugin code paths.

### Gaps
- None of these suggestions is validated against a real print-bureau API here (other researchers cover the services'
  APIs).
- Whether the PartCAD maintainers intend a remote daemon to carry `userConfig` as-is is not stated in the code beyond
  "once a daemon can be remote".
