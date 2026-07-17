"""CLI: validate a generated dataset and write its data-quality report.

Usage: python -m pipelines.data.validate --profile small [--data-root data]
Exit code 1 when validation fails thresholds.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from factoryguard.data.profiles import PROFILE_NAMES
from factoryguard.data.validation import validate_dataset
from factoryguard.utilities.logging import configure_logging

log = logging.getLogger("pipelines.data.validate")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=PROFILE_NAMES)
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args()

    configure_logging(fmt="console")
    dataset_dir = args.data_root / args.profile
    report = validate_dataset(dataset_dir)
    for name, t in report.tables.items():
        log.info(
            "%s: rows=%d schema=%d integrity=%d quarantined=%d %s",
            name,
            t.rows,
            t.schema_violations,
            t.integrity_violations,
            t.quarantined,
            "; ".join(t.notes),
        )
    log.info(
        "validation %s — report: %s",
        "PASSED" if report.passed else "FAILED",
        dataset_dir / "data-quality-report.json",
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
