#!/usr/bin/env bash
# Push local booking secrets to Railway without printing values.
# Prereq: railway login && railway link (to this service)
set -euo pipefail
cd "$(dirname "$0")/.."

if ! railway whoami >/dev/null 2>&1; then
  echo "Run: railway login"
  echo "Then: railway link   # pick advisor-appointment-scheduler"
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env"
  exit 1
fi

echo "Syncing env keys from .env (values hidden)..."
# shellcheck disable=SC1091
set -a
source .env
set +a

set_var() {
  local key="$1"
  local val="${2-}"
  if [[ -z "$val" ]]; then
    echo "skip $key (empty)"
    return 0
  fi
  railway variables set "${key}=${val}" >/dev/null
  echo "set  $key"
}

set_var GEMINI_API_KEY "${GEMINI_API_KEY-}"
set_var GEMINI_MODEL "${GEMINI_MODEL-}"
set_var GOOGLE_CALENDAR_ID "${GOOGLE_CALENDAR_ID-}"
set_var GOOGLE_DOCS_PREBOOKING_ID "${GOOGLE_DOCS_PREBOOKING_ID-}"
set_var GOOGLE_GMAIL_ADVISOR_TO "${GOOGLE_GMAIL_ADVISOR_TO-}"
set_var MCP_HTTP_BEARER_TOKEN "${MCP_HTTP_BEARER_TOKEN-}"
set_var MCP_SERVER_URL "${MCP_SERVER_URL-https://gmail-docs-mcp-server-production.up.railway.app/mcp}"
set_var SECURE_LINK_TEMPLATE "${SECURE_LINK_TEMPLATE-}"
set_var ADVICE_EDUCATIONAL_URL "${ADVICE_EDUCATIONAL_URL-}"
set_var APP_ENV production
set_var CORS_ORIGINS "https://advisor-appointment-scheduler-pd5t-eight.vercel.app"
set_var ELEVENLABS_AGENT_ID "${ELEVENLABS_AGENT_ID-}"
set_var VAPI_PUBLIC_KEY "${VAPI_PUBLIC_KEY-}"
set_var VAPI_ASSISTANT_ID "${VAPI_ASSISTANT_ID-}"

if [[ -f credentials.json ]]; then
  railway variables set "GOOGLE_CLIENT_SECRETS_JSON=$(cat credentials.json)" >/dev/null
  echo "set  GOOGLE_CLIENT_SECRETS_JSON (from credentials.json)"
else
  echo "skip GOOGLE_CLIENT_SECRETS_JSON (no credentials.json)"
fi

if [[ -f token.json ]]; then
  railway variables set "GOOGLE_TOKEN_JSON=$(cat token.json)" >/dev/null
  echo "set  GOOGLE_TOKEN_JSON (from token.json)"
else
  echo "skip GOOGLE_TOKEN_JSON (no token.json)"
fi

if [[ -n "${GOOGLE_SERVICE_ACCOUNT_JSON-}" ]]; then
  set_var GOOGLE_SERVICE_ACCOUNT_JSON "$GOOGLE_SERVICE_ACCOUNT_JSON"
fi

echo "Triggering redeploy..."
railway up --detach >/dev/null 2>&1 || railway redeploy -y >/dev/null 2>&1 || true
echo "Done. Wait ~1 min, then check:"
echo "  curl -s https://advisor-appointment-scheduler-production.up.railway.app/health"
echo "Expect phase4_side_effects: true"
