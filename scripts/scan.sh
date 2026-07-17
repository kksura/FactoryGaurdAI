#!/usr/bin/env bash
# Vulnerability scans via containers (no host installs).
# - trivy: filesystem + config (Dockerfile/compose/IaC) + image if built
# Results are printed and saved under reports/security/.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p reports/security

echo "[scan] trivy filesystem + config scan"
docker run --rm -v "$PWD:/src:ro" aquasec/trivy:latest fs \
  --scanners vuln,misconfig,secret --severity HIGH,CRITICAL --ignore-unfixed \
  /src | tee reports/security/trivy-fs.txt

if docker image inspect factoryguard-api:local >/dev/null 2>&1; then
  echo "[scan] trivy image scan"
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest \
    image --severity HIGH,CRITICAL --ignore-unfixed factoryguard-api:local \
    | tee reports/security/trivy-image.txt
fi
echo "[scan] reports in reports/security/"
