"""Issue a development JWT for the local API (ADR-0010; dev/test only).

Usage:
    python scripts/issue_dev_token.py --roles quality-engineer plant-viewer
        [--sub dev-user] [--ttl 3600]

Reads the HMAC secret from FG_AUTH__LOCAL_JWT_SECRET (or .env). The
hardened-environment config validator forbids this provider outside
local/test, so a leaked dev token is useless against staging/production.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import jwt


def _load_dotenv_secret() -> str:
    env = os.environ.get("FG_AUTH__LOCAL_JWT_SECRET", "")
    if env:
        return env
    dotenv = Path(".env")
    if dotenv.is_file():
        for line in dotenv.read_text().splitlines():
            if line.startswith("FG_AUTH__LOCAL_JWT_SECRET="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roles", nargs="+", required=True)
    parser.add_argument("--sub", default="dev-user")
    parser.add_argument("--ttl", type=int, default=3600)
    parser.add_argument("--issuer", default="factoryguard-local")
    parser.add_argument("--audience", default="factoryguard-api")
    args = parser.parse_args()

    secret = _load_dotenv_secret()
    if not secret:
        print("FG_AUTH__LOCAL_JWT_SECRET is not set (env or .env)", file=sys.stderr)
        return 1
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": args.sub,
            "roles": args.roles,
            "iss": args.issuer,
            "aud": args.audience,
            "iat": now,
            "exp": now + args.ttl,
        },
        secret,
        algorithm="HS256",
    )
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
