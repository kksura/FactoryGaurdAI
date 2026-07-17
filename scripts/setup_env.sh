#!/usr/bin/env bash
# Create the project venv and install pinned dependencies.
# Safe to re-run; only touches .venv/ and requirements/*.txt.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-python3.12}

if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi
. .venv/bin/activate

pip install --quiet --upgrade pip pip-tools

# Co-resolve every .in into one unified lock so cross-file conflicts are
# impossible. Recompile only when an .in is newer than the lock.
if [ ! -f requirements/lock.txt ] \
   || [ requirements/base.in -nt requirements/lock.txt ] \
   || [ requirements/ml.in -nt requirements/lock.txt ] \
   || [ requirements/dev.in -nt requirements/lock.txt ]; then
  echo "[setup] compiling requirements/lock.txt"
  pip-compile --quiet --strip-extras -o requirements/lock.txt \
    requirements/base.in requirements/ml.in requirements/dev.in
fi

echo "[setup] installing locked dependencies"
pip install --quiet -r requirements/lock.txt

echo "[setup] installing torch (CUDA aarch64 wheel, with fallbacks)"
if ! pip install --quiet -r requirements/torch.txt --index-url https://download.pytorch.org/whl/cu130 2>/tmp/torch_install.log; then
  echo "[setup] cu130 failed, trying cu129"
  if ! pip install --quiet -r requirements/torch.txt --index-url https://download.pytorch.org/whl/cu129 2>>/tmp/torch_install.log; then
    echo "[setup] CUDA wheels failed, falling back to CPU wheel from PyPI (GPU disabled)"
    pip install --quiet -r requirements/torch.txt
  fi
fi

echo "[setup] installing factoryguard (editable)"
pip install --quiet -e .

echo "[setup] done. Run 'make doctor' to verify the environment."
