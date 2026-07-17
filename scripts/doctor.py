#!/usr/bin/env python
"""Environment health check. Verifies, never assumes.

Exit code 0 = all required checks pass (GPU is reported but optional,
because CI and cloud CPU nodes are supported paths).
"""

from __future__ import annotations

import importlib
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_MODULES = [
    "numpy",
    "pandas",
    "pyarrow",
    "sklearn",
    "pydantic",
    "fastapi",
    "pandera",
    "networkx",
    "PIL",
    "yaml",
    "jwt",
]
OPTIONAL_MODULES = ["torch", "torchvision", "mlflow", "shap", "streamlit"]

OK, WARN, FAIL = "ok", "warn", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))


def main() -> int:
    check("python", OK if sys.version_info[:2] == (3, 12) else WARN, platform.python_version())
    check("platform", OK, f"{platform.system()} {platform.machine()}")

    for mod in REQUIRED_MODULES:
        try:
            m = importlib.import_module(mod)
            check(f"module:{mod}", OK, getattr(m, "__version__", ""))
        except ImportError as exc:
            check(f"module:{mod}", FAIL, str(exc))

    for mod in OPTIONAL_MODULES:
        try:
            m = importlib.import_module(mod)
            check(f"module:{mod}", OK, getattr(m, "__version__", ""))
        except ImportError:
            check(f"module:{mod}", WARN, "not installed (optional at this phase)")

    # GPU: optional but report honestly, including a real kernel launch.
    try:
        import torch

        if torch.cuda.is_available():
            dev = torch.cuda.get_device_name(0)
            a = torch.randn(256, 256, device="cuda")
            b = (a @ a).sum().item()  # forces a kernel launch
            check("gpu", OK, f"{dev}; matmul ok ({b:.1f}); torch cuda {torch.version.cuda}")
        else:
            check("gpu", WARN, "torch installed but CUDA not available (CPU path active)")
    except ImportError:
        check("gpu", WARN, "torch not installed")
    except Exception as exc:  # kernel launch failed — report, don't crash
        check("gpu", WARN, f"CUDA present but kernel launch failed: {exc}")

    for tool in ("docker", "git"):
        check(f"tool:{tool}", OK if shutil.which(tool) else WARN, shutil.which(tool) or "missing")

    if shutil.which("docker"):
        try:
            cmd = ["docker", "compose", "version"]  # fixed argv, no untrusted input
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)  # noqa: S603
            check("tool:docker-compose", OK if out.returncode == 0 else WARN, out.stdout.strip())
        except Exception as exc:
            check("tool:docker-compose", WARN, str(exc))

    env_file = Path(".env")
    example = Path(".env.example")
    if example.exists() and not env_file.exists():
        check("dotenv", WARN, ".env missing — copy .env.example and set real values")
    else:
        check("dotenv", OK, ".env present" if env_file.exists() else "no .env.example")

    # Config must load and hardened validation must reject insecure prod.
    try:
        from factoryguard.config import ConfigurationError, load_settings

        load_settings("test")
        check("config:test", OK, "loads and validates")
        try:
            load_settings("production")
            check("config:prod-fail-closed", FAIL, "insecure production config was ACCEPTED")
        except ConfigurationError:
            check("config:prod-fail-closed", OK, "insecure production config rejected")
    except Exception as exc:
        check("config:test", FAIL, str(exc))

    width = max(len(n) for n, _, _ in results)
    failed = False
    for name, status, detail in results:
        mark = {"ok": "✅", "warn": "⚠️ ", "FAIL": "❌"}[status]
        print(f"{mark} {name:<{width}}  {detail}")
        failed |= status == FAIL
    print()
    print("doctor: FAIL — required checks failed" if failed else "doctor: environment healthy")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
