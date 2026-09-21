#!/usr/bin/env bash
# Builds a deployment bundle containing ONLY what's needed to run this app
# (app.py + src/ + data/ + pyproject.toml + the bridge's deployment doc)
# inside the NemoClaw sandbox at /sandbox/tender-assistant.
#
# This script only builds a local tarball on THIS machine — it does not
# upload, connect to, or otherwise reach the NemoClaw sandbox (there is no
# network path from this environment to do so; see
# deploy/simap-bridge/README.md). Getting the resulting tarball into
# /sandbox/tender-assistant is a separate, manual step performed by whoever
# has access to the NemoClaw dashboard's upload flow.
#
# Usage:
#   deploy/build_bundle.sh [output_path]
#   (default output_path: dist/tender-assistant-bundle.tar.gz)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_PATH="${1:-"$REPO_ROOT/dist/tender-assistant-bundle.tar.gz"}"

STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT

cd "$REPO_ROOT"

# --- app.py -------------------------------------------------------------
cp app.py "$STAGE_DIR/app.py"

# --- pyproject.toml -------------------------------------------------------
cp pyproject.toml "$STAGE_DIR/pyproject.toml"

# --- src/ (all source, no caches) -----------------------------------------
mkdir -p "$STAGE_DIR/src"
find src -type f -name "*.py" -print0 | while IFS= read -r -d '' f; do
    mkdir -p "$STAGE_DIR/$(dirname "$f")"
    cp "$f" "$STAGE_DIR/$f"
done

# --- data/ (fixtures + HPE profile only -- no gitignored runtime state) ---
mkdir -p "$STAGE_DIR/data"
cp data/hpe_profile.json "$STAGE_DIR/data/hpe_profile.json"
cp data/sample_tenders.json "$STAGE_DIR/data/sample_tenders.json"
find data/sample_tenders -type f -print0 | while IFS= read -r -d '' f; do
    mkdir -p "$STAGE_DIR/$(dirname "$f")"
    cp "$f" "$STAGE_DIR/$f"
done
# Deliberately NOT copied: data/feedback_log.json (gitignored, runtime
# human-review state from THIS machine — a fresh sandbox deployment must
# not ship with someone else's review history), data/briefings/ (same
# reasoning, MCP-tool-written runtime output).

# --- files necessary for the bridge ---------------------------------------
mkdir -p "$STAGE_DIR/deploy/simap-bridge"
cp deploy/simap-bridge/README.md "$STAGE_DIR/deploy/simap-bridge/README.md"
# The bridge's own code is already included above as part of src/
# (src/simap_bridge.py, src/adapters/simap_bridge_client.py,
# src/adapters/tender_search.py) -- nothing bridge-specific lives outside
# src/ except this deployment doc.

mkdir -p "$(dirname "$OUT_PATH")"
tar -czf "$OUT_PATH" -C "$STAGE_DIR" .

echo "Bundle written to: $OUT_PATH"
echo "Contents:"
tar -tzf "$OUT_PATH" | sort
echo
echo "This is a LOCAL tarball only. To deploy it:"
echo "  1. Upload $OUT_PATH into the NemoClaw sandbox (dashboard upload flow --"
echo "     no nemohermes/hermes CLI is available from this environment)."
echo "  2. Inside the sandbox: mkdir -p /sandbox/tender-assistant && \\"
echo "     tar -xzf <uploaded-file> -C /sandbox/tender-assistant"
echo "  3. Follow deploy/simap-bridge/README.md from there."
