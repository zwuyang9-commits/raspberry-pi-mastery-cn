"""Validate environment settings before starting the local device API."""

from __future__ import annotations

import argparse
import json

from rpi_mastery.deployment import DeploymentConfig, DeploymentConfigError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    try:
        config = DeploymentConfig.from_env()
        checks = config.require_safe()
    except DeploymentConfigError as error:
        if args.json:
            print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        else:
            print(f"部署预检失败：{error}")
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "host": config.host,
                    "port": config.port,
                    "checks": [check.__dict__ for check in checks],
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"部署预检通过：{config.host}:{config.port}")
        for check in checks:
            print(f"- {check.name}: {check.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
