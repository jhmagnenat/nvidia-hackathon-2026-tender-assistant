#!/usr/bin/env node
/**
 * Stderr-only startup diagnostic for the SIMAP MCP server.
 *
 * Hermes/NemoClaw launches this file instead of @digilac/simap-mcp's
 * dist/index.js directly — same `node --use-env-proxy` command, same env,
 * only the script argument changes (see hermes-config.example.yaml). It
 * prints non-secret environment/network facts to stderr, then hands off to
 * the real simap-mcp entrypoint in the *same* process, so MCP stdio
 * behavior (what Hermes actually talks to) is completely unchanged.
 *
 * Why this exists: "Network or timeout error while retrieving cantons" is a
 * generic message @digilac/simap-mcp emits whenever fetch() fails before any
 * HTTP response arrives (DNS / connection / TLS / its own 30s timeout) — see
 * README.md "Troubleshooting". That message alone cannot say *which* of
 * those it was, and the difference between "the process never even saw
 * HTTP_PROXY" and "HTTP_PROXY was set but the CA file it needs isn't there"
 * is exactly the difference between two separate fixes. This block runs
 * once per server start and always appears first on stderr, before any tool
 * is even called, so the answer is available immediately instead of
 * requiring a guess.
 *
 * Deliberately prints ONLY:
 *   - whether HTTP_PROXY / HTTPS_PROXY / NODE_USE_ENV_PROXY are set (never
 *     their value — a proxy URL can carry embedded basic-auth credentials);
 *   - whether NODE_EXTRA_CA_CERTS / SSL_CERT_FILE are set, and, if so, their
 *     *path* (a filesystem path is not a secret) plus whether that path
 *     exists and is readable (never the certificate's content);
 *   - hostname and Node version;
 *   - whether --use-env-proxy was actually passed to this process.
 * Never prints a full proxy URL or any certificate bytes.
 */
import { accessSync, constants as fsConstants, existsSync } from "node:fs";
import { hostname } from "node:os";
import { pathToFileURL } from "node:url";

function logCaFileVar(envVar) {
    const value = process.env[envVar];
    if (!value) {
        console.error(`  ${envVar}: not set`);
        return;
    }
    const exists = existsSync(value);
    let readable = false;
    if (exists) {
        try {
            accessSync(value, fsConstants.R_OK);
            readable = true;
        } catch {
            readable = false;
        }
    }
    console.error(`  ${envVar}: set, path=${value}, exists=${exists}, readable=${readable}`);
}

function runDiagnostics() {
    console.error("=== simap-mcp preflight (env/network facts only, no secrets) ===");
    console.error(`  hostname: ${hostname()}`);
    console.error(`  node: ${process.version}`);
    console.error(`  --use-env-proxy passed to this process: ${process.execArgv.includes("--use-env-proxy")}`);
    console.error(`  HTTP_PROXY: ${process.env.HTTP_PROXY ? "set" : "not set"}`);
    console.error(`  HTTPS_PROXY: ${process.env.HTTPS_PROXY ? "set" : "not set"}`);
    console.error(`  NODE_USE_ENV_PROXY: ${process.env.NODE_USE_ENV_PROXY ? "set" : "not set"}`);
    logCaFileVar("NODE_EXTRA_CA_CERTS");
    logCaFileVar("SSL_CERT_FILE");
    console.error("=== end preflight — starting real simap-mcp server now ===");
}

async function main() {
    const target = process.argv[2];
    if (!target) {
        console.error(
            "preflight.mjs: missing required argv[2] (path to @digilac/simap-mcp's dist/index.js). " +
                "Not starting — fix the `args` list in the Hermes MCP server config."
        );
        process.exit(1);
    }

    try {
        runDiagnostics();
    } catch (error) {
        // A bug in the diagnostic block must never block the real server from
        // starting — log it and continue to the handoff below regardless.
        console.error("preflight.mjs: diagnostic block failed (continuing to start the real server):", error);
    }

    await import(pathToFileURL(target).href);
}

main();
