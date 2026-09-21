# Deploying the app + SIMAP MCP bridge inside the NemoClaw sandbox

Target layout, all inside the **same** NemoClaw sandbox as `simap-fixed`
(confirmed already running there):

```
NemoClaw Sandbox
├── simap-fixed MCP                (already running — not part of this bundle)
├── SIMAP bridge   — 127.0.0.1:8135  (loopback only, never exposed)
└── Streamlit      — 0.0.0.0:8507    (the one port that should be exposed)
```

`src/simap_bridge.py` relays `search_tenders`/`get_tender_details`/`list_cantons`
MCP tool calls over HTTP for anything that can't speak MCP stdio directly —
read its module docstring for what it does and why. With Streamlit now
deployed in the *same* sandbox as `simap-fixed`, the bridge only ever needs
to answer `127.0.0.1` — no port forwarding between this dev VM and the
sandbox, and no exposure of the bridge port, is proposed anywhere below.

**Not runnable from this repo's own environment.** `nemohermes`/`hermes` are
not on this VM's `PATH` (confirmed repeatedly — see `NVIDIA_AUDIT.md`,
`IMPLEMENTATION_LOG.md`). Every step below is a manual procedure for
whoever has access to the NemoClaw/OpenShell sandbox, via the BREV-NVIDIA
LaunchPad dashboard — not this VM's terminal.

## 1. Build the deployment bundle (run on this dev machine)

```bash
deploy/build_bundle.sh
# -> dist/tender-assistant-bundle.tar.gz
```

Contains **only**: `app.py`, `src/` (all of it — includes the bridge:
`src/simap_bridge.py`, `src/adapters/simap_bridge_client.py`,
`src/adapters/tender_search.py`), `data/` (`hpe_profile.json`,
`sample_tenders.json`, `sample_tenders/*` — *not* the gitignored
`data/feedback_log.json` runtime state), `pyproject.toml`, and
`deploy/simap-bridge/README.md` (this file). No tests, no `.git`, no other
docs. This script only writes a local tarball — it does not upload or
otherwise reach the sandbox.

## 2. Upload and extract into `/sandbox/tender-assistant`

Via the NemoClaw dashboard's file upload/file-manager surface (no
`nemohermes upload` CLI is available from this VM to script it):

```bash
mkdir -p /sandbox/tender-assistant
tar -xzf tender-assistant-bundle.tar.gz -C /sandbox/tender-assistant
cd /sandbox/tender-assistant
```

## 3. Install dependencies (inside the sandbox)

```bash
pip install -e ".[bridge]"
```

Installs `pydantic`, `python-dotenv`, `streamlit`, `mcp` (from
`pyproject.toml`'s main deps) plus `starlette`/`uvicorn` (the `bridge`
extra, needed only to run `src/simap_bridge.py`).

## 4. Start the bridge — 127.0.0.1:8135, loopback only

Reuse the exact SIMAP_MCP_* env values already active on `simap-fixed`'s own
Hermes entry (copy them from there — do not retype from memory or guess):

```bash
export SIMAP_MCP_ENTRYPOINT=/sandbox/.hermes/mcp/simap/simap-mcp/node_modules/@digilac/simap-mcp/dist/index.js
export SIMAP_MCP_NODE_COMMAND=/usr/local/bin/node   # only if "node" alone doesn't resolve
export HTTP_PROXY=...      # copy the real value from the simap-fixed entry
export HTTPS_PROXY=...
export NODE_EXTRA_CA_CERTS=...
export SSL_CERT_FILE=...
export NODE_USE_ENV_PROXY=1

export SIMAP_BRIDGE_HOST=127.0.0.1
export SIMAP_BRIDGE_PORT=8135

python -m src.simap_bridge
```

**Test — `/health`:**

```bash
curl http://127.0.0.1:8135/health
```

A `{"status": "ok", ...}` response with `"# Swiss Cantons"` in
`response_preview` is the only acceptable proof this is actually working —
anything else (`"unavailable"`, `"error"`, connection refused) means fix the
SIMAP_MCP_* env above before going further, the same way `simap-fixed`
itself was debugged (see `integrations/simap/README.md` "Troubleshooting").
Do not proceed to step 5 until this returns `"status": "ok"`.

## 5. Start Streamlit — 0.0.0.0:8507

In a second shell/process, same sandbox, same directory:

```bash
export SIMAP_BRIDGE_URL=http://127.0.0.1:8135
streamlit run app.py --server.port 8507 --server.address 0.0.0.0
```

`SIMAP_BRIDGE_URL` is what makes `src/adapters/simap_bridge_client.py::SimapBridgeAdapter`
`.available` — without it, the app still runs (it falls back to
`LocalSampleSearchAdapter`), it just won't reach the bridge. Since both
processes are now in the same sandbox, `127.0.0.1:8135` genuinely resolves —
no forwarding, tunnel, or ingress config is needed for the bridge itself.

**Test — Streamlit is actually up:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8507
```

Expect `200`. (Run this inside the sandbox — it only proves the process is
listening there, not that it's reachable from outside; see step 6.)

## 6. Confirm the whole chain with a real search

In the Streamlit UI (or via `python -m src.pipeline search "cloud infrastructure"`
from the same shell/env), run a search and check the result's source:

- **`source_type: "simap_mcp"`** / UI shows **"SIMAP"** → the bridge → MCP →
  `www.simap.ch` chain worked end to end. This is the only condition under
  which this deployment may be described as "live."
- **`source_type: "local_fallback"`** / UI shows **"Local Sample"** → the
  bridge call failed somewhere (check `/health` again, check the bridge
  process's own stderr) — this is the honest, working fallback, not a bug,
  but it means SIMAP is *not* actually being used yet.

## 7. Exposure — only port 8507

Once both processes are confirmed running and the search test above shows
`simap_mcp`, the *only* port that should be opened to anything outside the
sandbox is **8507** (Streamlit). Port **8135** (the bridge) must stay bound
to `127.0.0.1` and must never be exposed, forwarded, or added to any
ingress/firewall rule — it has no authentication layer and is meant purely
for this sandbox's own Streamlit process to call over loopback. This
document does not propose or configure that external-facing exposure for
8507 either (e.g. via the same ingress pattern documented in
`deploy/hermes-ingress/`) — that remains a decision for whoever operates the
sandbox's network/security posture.

## What this document does NOT claim

No step above has been executed against the real NemoClaw sandbox from this
repo's environment — there is no network path from here to do so (confirmed
throughout `IMPLEMENTATION_LOG.md`). Every piece of *code* referenced here
(`src/simap_bridge.py`, `SimapBridgeAdapter`, `deploy/build_bundle.sh`) has
been tested/verified on this machine: the bundle script produces a working,
self-contained tarball (verified by extracting it to a clean directory and
running a real search against it, which correctly fell back to
`local_fallback` since no bridge was running there), and the bridge/client
code round-trips real HTTP + real MCP protocol against a fake stand-in
server (`tests/test_simap_bridge.py`, `tests/adapters/test_simap_bridge_client.py`).
None of that proves the two real processes are running together inside the
actual NemoClaw sandbox — **do not report this deployment as done until
both `simap-fixed`, the bridge (step 4), and Streamlit (step 5) have
actually been started together in that same sandbox, and step 6's search
test has actually shown `simap_mcp`.**
