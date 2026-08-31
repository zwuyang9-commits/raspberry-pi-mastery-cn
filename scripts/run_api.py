"""Safely start the local device API from validated environment settings."""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from rpi_mastery.deployment import DeploymentConfig, DeploymentConfigError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration without starting the server",
    )
    args = parser.parse_args()

    try:
        config = DeploymentConfig.from_env()
        config.require_safe()
    except DeploymentConfigError as error:
        print(f"拒绝启动：{error}")
        return 1

    if args.check:
        print(f"安全启动配置有效：{config.host}:{config.port}")
        return 0

    try:
        import uvicorn
    except ImportError:
        print('缺少 Web 依赖，请先运行 pip install -e ".[web]"')
        return 1

    repository_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository_root))
    app = importlib.import_module("projects.03_local_device_api.main").app
    uvicorn.run(app, host=config.host, port=config.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
