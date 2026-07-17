#!/usr/bin/env bash
# Generate SBOMs for the Python environment and (if built) the API image
# using syft via container (no host install). Output: sbom/
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p sbom

echo "[sbom] python dependencies (from lock file)"
docker run --rm -v "$PWD:/src:ro" -w /src anchore/syft:latest \
  file:requirements/lock.txt -o spdx-json > sbom/python-deps.spdx.json

if docker image inspect factoryguard-api:local >/dev/null 2>&1; then
  echo "[sbom] container image factoryguard-api:local"
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock anchore/syft:latest \
    factoryguard-api:local -o spdx-json > sbom/image.spdx.json
else
  echo "[sbom] image factoryguard-api:local not built; skipping image SBOM"
fi
echo "[sbom] wrote $(ls sbom/)"
