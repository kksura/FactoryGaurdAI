#!/usr/bin/env bash
# FactoryGuard AI — non-prod teardown (Phase 7; NEVER run from the GB10).
# Deletes the whole spoke resource group after explicit confirmation.
# Prod is protected twice: this script refuses env=prod, and the RG carries a
# CanNotDelete lock that must be removed via the documented change process.
#
# Usage: scripts/azure/teardown.sh <dev|staging>
# Env vars: AZ_SUBSCRIPTION (required)

set -euo pipefail

ENVIRONMENT="${1:?usage: teardown.sh <dev|staging>}"
if [[ "$ENVIRONMENT" == "prod" ]]; then
  echo "ERROR: refusing to tear down prod. Follow the decommission procedure in" >&2
  echo "docs/operations/azure-deployment-runbook.md §9 (lock removal, backups, sign-off)." >&2
  exit 2
fi

: "${AZ_SUBSCRIPTION:?set AZ_SUBSCRIPTION to the target subscription id}"
az account set --subscription "$AZ_SUBSCRIPTION"
RG="rg-fg-$ENVIRONMENT"

az group show --name "$RG" >/dev/null || { echo "resource group $RG not found"; exit 0; }

echo "About to DELETE resource group $RG and everything in it:"
az resource list --resource-group "$RG" --query '[].{name:name,type:type}' -o table

read -r -p "Type the resource group name to confirm deletion: " CONFIRM
[[ "$CONFIRM" == "$RG" ]] || { echo "aborted."; exit 3; }

# Key Vault has purge protection: deletion leaves a soft-deleted vault that
# blocks name reuse until the retention window lapses — that is intentional.
az group delete --name "$RG" --yes
echo "Deletion started (runs async). Budgets scoped to the RG stop accruing with it."
echo "Note: subscription-level deployment metadata and the soft-deleted Key Vault remain."
