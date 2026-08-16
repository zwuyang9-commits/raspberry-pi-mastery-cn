from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from ipaddress import ip_address
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from rpi_mastery.hardware import DigitalOutput, SimulatedDigitalOutput


class OutputCommand(BaseModel):
    value: float


def _is_loopback(request: Request) -> bool:
    if request.client is None:
        return False
    try:
        return ip_address(request.client.host).is_loopback
    except ValueError:
        return request.client.host == "testclient"


def create_app(
    *,
    output: DigitalOutput | None = None,
    token: str | None = None,
) -> FastAPI:
    """Create an API whose writes stay local unless a token is configured."""

    device_output = output if output is not None else SimulatedDigitalOutput()
    write_token = token if token is not None else os.getenv("RPI_API_TOKEN")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        device_output.close()

    api = FastAPI(title="树莓派本地设备 API", version="1.1", lifespan=lifespan)

    def require_write_access(
        request: Request,
        supplied_token: Annotated[str | None, Header(alias="X-API-Token")] = None,
    ) -> None:
        if write_token:
            if supplied_token is None or not hmac.compare_digest(supplied_token, write_token):
                raise HTTPException(401, "X-API-Token 不正确")
            return
        if not _is_loopback(request):
            raise HTTPException(403, "局域网写入前请先设置 RPI_API_TOKEN")

    @api.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "mode": "simulated",
            "write_protection": "token" if write_token else "loopback-only",
        }

    @api.get("/output")
    def get_output() -> dict[str, float]:
        return {"value": device_output.value}

    @api.put("/output")
    def set_output(
        command: OutputCommand,
        _: Annotated[None, Depends(require_write_access)],
    ) -> dict[str, float]:
        if not 0.0 <= command.value <= 1.0:
            raise HTTPException(422, "value 必须在 0 与 1 之间")
        device_output.set(command.value)
        return {"value": device_output.value}

    return api


app = create_app()
