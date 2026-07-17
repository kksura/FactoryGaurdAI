"""CLI: generate a synthetic dataset profile.

Usage: python -m pipelines.data.generate --profile small [--data-root data]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from factoryguard.data.generate import generate_dataset
from factoryguard.data.profiles import PROFILE_NAMES
from factoryguard.utilities.logging import configure_logging

log = logging.getLogger("pipelines.data.generate")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()

    configure_logging(fmt="console")
    out = generate_dataset(args.profile, data_root=args.data_root)
    log.info("dataset written to %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
