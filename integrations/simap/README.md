# SIMAP MCP for Hermes

Verified in the workshop on 14 September 2026: 14 tools discovered; direct and real in-agent calls returned 26 cantons and software tenders with source links. Missing proxy/CA subprocess settings caused earlier connectivity failures. Application ingestion integration remains separate work.

## Installation

Run `npm ci --ignore-scripts` in this directory in an isolated install location. The lockfile comes from the deployed host tree, with the direct dependency pinned to its resolved 1.4.0. Validate in a separate environment before replacing the running installation. Transfer the installed directory to `/sandbox/.hermes/mcp/simap` using the supported upload flow (`nemohermes tender-assistant upload --help`). Keep dependencies out of Git. The Node runtime must support `--use-env-proxy`.

From the repository root, deliberately apply the preset with `nemohermes tender-assistant policy add --from-file integrations/simap/policy.yaml --yes`. It permits only Node HTTPS GET requests to `www.simap.ch/api/**`. Public discovery requires no account key; protected documents are not covered by these tests.

## Registration

Use native Hermes stdio registration (`hermes mcp add --help`); NemoClaw 0.0.123 managed MCP registration supports HTTP servers. Merge `hermes-config.example.yaml` into the intended profile without replacing unrelated settings. The workshop registered both base and dashboard profiles; paths are in [the runbook](../../docs/NEMOHERMES_SETUP.md). Verify proxy and certificate paths inside the actual sandbox namespace. Preserve TLS verification.

The example includes the recovery settings applied to the base profile: `connect_timeout: 10` and `lazy: true`. Lazy discovery uses a matching schema cache when available, otherwise it connects normally. This is not proof of the original outage cause.

## Applying the active configuration from the BREV-NVIDIA / NemoClaw dashboard (no CLI)

The `nemohermes`/`hermes` CLI is not available in this project's VM terminal
— only the BREV-NVIDIA LaunchPad's NemoClaw/Hermes web UI is. Everything
below is the same change the CLI commands above would make
(`hermes mcp add`, uploading a file to `/sandbox/.hermes/mcp/simap/`),
expressed as manual steps in that UI instead. Exact widget/menu labels are
not verified here (this VM has no access to render that UI) — locate the
nearest equivalent control for each step; the *data* below (paths, args, env
keys) is exact and must not be changed except where explicitly marked
sandbox-specific.

1. **Upload `integrations/simap/preflight.mjs` to the sandbox filesystem**,
   next to the existing SIMAP install, as
   `/sandbox/.hermes/mcp/simap/preflight.mjs`. Use whatever file-upload/file-
   manager surface the NemoClaw dashboard exposes for that sandbox (the same
   one used for the original `nemohermes tender-assistant upload` deployment
   in Installation, above, just done through the UI instead of the CLI).
   This file has **no dependencies** (plain Node `fs`/`os`/`url` built-ins
   only) — it does not need `npm ci`/`npm install` run against it.
2. **Open the MCP servers screen in Hermes** (the one where the `simap`
   server entry is currently listed — this is the "écran MCP Hermes"
   referenced in this task) and edit that entry's **Args** field. Today it
   ends in a single path:
   `/sandbox/.hermes/mcp/simap/simap-mcp/node_modules/@digilac/simap-mcp/dist/index.js`
   (confirmed as the currently active path — do not change it). Change the
   args list so it becomes **two** path entries after `--use-env-proxy`,
   in this exact order:
   1. `/sandbox/.hermes/mcp/simap/preflight.mjs`
   2. `/sandbox/.hermes/mcp/simap/simap-mcp/node_modules/@digilac/simap-mcp/dist/index.js` (unchanged — this becomes the wrapper's `argv[2]`)

   `command` stays `/usr/local/bin/node`; do not add or remove
   `--use-env-proxy`. This exactly matches
   `integrations/simap/hermes-config.example.yaml` in this repo — the
   simplest way to apply it correctly is to open that file and copy the
   `args:` list verbatim into the dashboard's Args field.
3. **Leave the `env` block exactly as currently configured** —
   `NODE_USE_ENV_PROXY`, `HTTP_PROXY`, `HTTPS_PROXY`, `NODE_EXTRA_CA_CERTS`,
   `SSL_CERT_FILE` are already present per this task's confirmed context, and
   none of their *values* should be guessed or edited from outside the
   sandbox (see Troubleshooting below for why). Optionally add
   `SIMAP_MCP_DEBUG: "1"` (present in `hermes-config.example.yaml`) if it
   isn't already set — it only adds request-URL/timing detail to stderr on
   top of what `preflight.mjs` already prints, no behavior change.
4. **No `policy.yaml` change is needed.** `preflight.mjs` runs inside the
   same `/usr/local/bin/node` process as the real server (it `import()`s the
   real entrypoint in-process rather than spawning a new one) — the
   `binaries: [{ path: /usr/local/bin/node }]` rule in `policy.yaml` still
   matches unchanged, and the outbound request is still the same
   `GET https://www.simap.ch/api/**` the policy already allows.
5. **Restart just the `simap` MCP server** from that same screen (whatever
   control restarts/reconnects one server — commonly labeled Restart/
   Reconnect/Disconnect+Connect next to the entry), or restart the sandbox
   container if no per-server control exists. A full `nemohermes`-driven
   redeploy is not required for this change — only the args/file update
   above.
6. **Trigger `list_cantons` again** from a fresh Hermes chat, then read this
   server's stderr log from the dashboard's log viewer for that MCP server.
   The very first lines will now be the `preflight.mjs` block described in
   Troubleshooting below, before anything else — that block, not the chat
   error text, is what actually answers "which of the 4 candidate causes is
   it."

## Validation

Check 14 tools in the intended profiles. Call `list_cantons` and `search_tenders(search=software)`, then repeat through a fresh Hermes chat asking for source links. Discovery alone does not prove connectivity. Keep raw session and API evidence outside Git. Preserve the application local-PDF path while adding live discovery.

## Troubleshooting: "Network or timeout error while retrieving cantons"

Root-caused by reading `@digilac/simap-mcp@1.4.0`'s compiled source (`npm pack`
into `/tmp`, never installed into this repo — see
`dist/tools/codes/list-cantons.js`, `dist/api/client.js`,
`dist/utils/errors.js`) and reproducing the failure locally. Findings:

- `list_cantons` calls `GET https://www.simap.ch/api/cantons/v1`
  (`dist/api/endpoints.js`, `ENDPOINTS.CANTONS`) — a real, live endpoint.
  Confirmed directly: it returns `HTTP 200` with the 26-canton JSON body.
  **The endpoint is correct and reachable from the public internet; this is
  not an endpoint or API-contract bug.**
- `policy.yaml`'s `path: "/api/**"` rule already covers `/api/cantons/v1` —
  **not a policy-pattern bug** either.
- **This exact message can only come from the HTTP request itself never
  completing** — a `fetch()` exception (DNS failure, connection refused,
  proxy/TLS failure, or the client's own 30s abort timeout) caught by
  `isNetworkOrTimeoutError()` in `dist/utils/errors.js`. A genuine HTTP
  response from simap — including 403/404/405 — takes a *different* code
  path (`SimapApiError`) and produces a *different*, clearly distinguishable
  message ("simap rejected the request... (HTTP 4xx)" / "The requested
  resource was not found on simap"). Reproduced locally: pointing
  `HTTP_PROXY`/`HTTPS_PROXY` at an unreachable or non-existent proxy host
  makes the identical Node `fetch()` call fail with `TypeError: fetch
  failed`, which is exactly what gets reported to Hermes as "Network or
  timeout error while retrieving cantons." **So the observed message is not
  proof of a real timeout — it's proof the request never got a response at
  all**, which is consistent with several distinct causes that this message
  alone cannot distinguish between:
  1. `HTTP_PROXY`/`HTTPS_PROXY` (`10.200.0.1:3128` in the example config)
     is not the correct or not a reachable proxy address *from the network
     namespace the SIMAP MCP subprocess actually runs in*.
  2. `NODE_EXTRA_CA_CERTS` / `SSL_CERT_FILE` don't point to a real,
     readable CA bundle in that same namespace — needed if the egress proxy
     TLS-terminates HTTPS to enforce `policy.yaml`'s method/path rule (that
     rule only makes sense if the proxy inspects decrypted requests).
  3. The `nemohermes tender-assistant policy add --from-file
     integrations/simap/policy.yaml --yes` step (see Installation) was
     never run, or was run against a stale policy, so the sandbox's default
     egress policy blocks the `CONNECT` to `www.simap.ch:443` outright — a
     proxy-level policy rejection typically surfaces to the client as the
     same kind of connection failure, not as an HTTP 403 response.
  4. A **testing-from-the-wrong-namespace false positive**: a reachability
     check run from the general Sandbox Terminal does not prove the SIMAP
     MCP subprocess (spawned by Hermes with this exact command/env) can
     reach simap.ch, if that subprocess runs in a different, more
     restricted network namespace. This is not hypothetical here — the 14
     September incident in [`docs/NEMOHERMES_SETUP.md`](../../docs/NEMOHERMES_SETUP.md)
     records exactly this failure mode ("a direct probe outside that
     namespace was misleading").
- **The real underlying Node error is already being logged**, independent
  of the `SIMAP_MCP_DEBUG` flag: `toToolErrorResult()` in
  `dist/utils/errors.js` unconditionally does `console.error("list_cantons
  error:", error)` before returning the generic text, and Node's default
  error formatting prints the `cause` chain — so `ECONNREFUSED` /
  `ENOTFOUND` / `ETIMEDOUT` / a TLS certificate error / an
  `AbortError`/`TimeoutError` from the client's own 30s cutoff will each be
  visible verbatim in this MCP server's **stderr**, which Hermes captures
  separately from the chat-visible tool result text. `SIMAP_MCP_DEBUG=1`
  (added to `hermes-config.example.yaml`) additionally logs the exact
  request URL and, once fixed, response status/size/duration — useful to
  confirm the fix, not required to see the failure cause.

**Next diagnostic step (must run inside the actual Hermes/OpenShell
sandbox — not reachable from this repo's environment):** inspect this MCP
server process's stderr log for the *next* `list_cantons` failure and match
the underlying Node error against the table above (`ECONNREFUSED`/`ENOTFOUND`
on the proxy → cause 1; a certificate error → cause 2; connection
reset/refused straight to `simap.ch` with no proxy-hop detail → cause 3; a
clean success from a manual probe but the same failure from Hermes → cause
4). Fix the specific cause identified, then redeploy per Installation/
Registration above — do not guess or hardcode different values without that
stderr evidence.

### `preflight.mjs`: making that stderr evidence available without guessing

`integrations/simap/preflight.mjs` is a small, dependency-free wrapper that
Hermes launches in place of `dist/index.js` (see
`hermes-config.example.yaml` and "Applying the active configuration..."
above). It runs *inside the same process*, prints the following to stderr,
then hands off to the real server unchanged:

- whether `HTTP_PROXY` / `HTTPS_PROXY` / `NODE_USE_ENV_PROXY` are set (never
  their value — a proxy URL can embed basic-auth credentials);
- whether `NODE_EXTRA_CA_CERTS` / `SSL_CERT_FILE` are set, and if so their
  path plus whether that path exists and is readable *in the exact process
  Hermes actually launches* (never the certificate's content);
- hostname and Node version;
- whether `--use-env-proxy` was actually received by this process
  (`process.execArgv`).

This turns "cause 1 vs. 2 vs. 3 vs. 4" above from a guess into a direct
read: e.g. `HTTPS_PROXY: not set` despite the Hermes config listing one
means the env block isn't reaching the process at all (a Hermes/registration
problem, not a network one); `NODE_EXTRA_CA_CERTS: set, path=..., exists=false`
means cause 2, precisely; both env vars `set`/`exists=true`/`readable=true`
and `--use-env-proxy: true`, yet `list_cantons` still fails, points at cause
1 (proxy address wrong/unreachable) or cause 3 (policy not applied) instead
— check the proxy's own reachability/logs and whether `nemohermes
tender-assistant policy add` (Installation, above) actually ran, next.

Verified locally (package downloaded with `npm pack` into `/tmp`, never
installed in this repo or the project's `node_modules`): invoking
`node --use-env-proxy integrations/simap/preflight.mjs <path-to-dist/index.js>`
prints exactly the fields above with no secret values, then transfers
control into the real `dist/server.js` in the same process — the handoff is
transparent; MCP behavior seen by a client is identical to invoking
`dist/index.js` directly.
