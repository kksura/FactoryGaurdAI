#!/usr/bin/env bash
# FactoryGuard AI — Azure deployment driver (Phase 7; NEVER run from the GB10
# development environment). Wraps the ordered procedure in
# docs/operations/azure-deployment-runbook.md: auth → subscription → guards →
# what-if → (confirmed) deploy. Application/AML steps stay separate on purpose.
#
# Usage:
#   scripts/azure/deploy.sh <env> plan            # what-if only (safe)
#   scripts/azure/deploy.sh <env> apply           # what-if, confirm, deploy
# Env vars: AZ_SUBSCRIPTION (required), AZ_LOCATION (default westeurope)

set -euo pipefail

ENVIRONMENT="${1:?usage: deploy.sh <dev|staging|prod> <plan|apply>}"
ACTION="${2:?usage: deploy.sh <dev|staging|prod> <plan|apply>}"
LOCATION="${AZ_LOCATION:-westeurope}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="$REPO_ROOT/infrastructure/bicep/main.bicep"
PARAMS="$REPO_ROOT/infrastructure/bicep/environments/${ENVIRONMENT}.bicepparam"

[[ "$ACTION" == "plan" || "$ACTION" == "apply" ]] || { echo "action must be plan|apply" >&2; exit 2; }
[[ -f "$PARAMS" ]] || { echo "no parameter file for env '$ENVIRONMENT' ($PARAMS)" >&2; exit 2; }

# --- guard 1: no placeholders left in the parameter file ---------------------
if grep -nE '<[a-z-]+>' "$PARAMS"; then
  echo "ERROR: unresolved <placeholders> in $PARAMS — fill org values first (runbook §3)." >&2
  exit 3
fi

# --- guard 2: authenticated az session against the intended subscription -----
command -v az >/dev/null || { echo "ERROR: az CLI not installed." >&2; exit 3; }
az account show >/dev/null 2>&1 || { echo "ERROR: not logged in (az login / OIDC)." >&2; exit 3; }
: "${AZ_SUBSCRIPTION:?set AZ_SUBSCRIPTION to the target subscription id}"
az account set --subscription "$AZ_SUBSCRIPTION"
echo "Subscription: $(az account show --query '[name,id]' -o tsv | paste -sd' ')"

# --- guard 3: template compiles cleanly --------------------------------------
az bicep build --file "$TEMPLATE" --stdout > /dev/null
echo "bicep build: OK"

# --- what-if (always) --------------------------------------------------------
echo "=== what-if ($ENVIRONMENT @ $LOCATION) ==="
az deployment sub what-if \
  --name "factoryguard-$ENVIRONMENT" \
  --location "$LOCATION" \
  --template-file "$TEMPLATE" \
  --parameters "$PARAMS"

[[ "$ACTION" == "plan" ]] && { echo "Plan only — no changes applied."; exit 0; }

# --- apply (interactive confirmation; CI uses environment approval instead) --
if [[ -t 0 ]]; then
  read -r -p "Apply the changes above to '$ENVIRONMENT'? Type the environment name to confirm: " CONFIRM
  [[ "$CONFIRM" == "$ENVIRONMENT" ]] || { echo "aborted."; exit 4; }
fi

az deployment sub create \
  --name "factoryguard-$ENVIRONMENT" \
  --location "$LOCATION" \
  --template-file "$TEMPLATE" \
  --parameters "$PARAMS" \
  --output table

echo "Infra deployed. Next steps (runbook §5+): upload data, create AML assets,"
echo "run training, register/promote, deploy endpoints, smoke tests."
