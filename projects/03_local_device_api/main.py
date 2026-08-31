from __future__ import annotations

import hmac
import os
import re
from collections import OrderedDict
from contextlib import asynccontextmanager
from ipaddress import ip_address
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel

from rpi_mastery.audit import AuditLog
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
    audit: AuditLog | None = None,
    idempotency_cache_size: int = 1000,
    mode: str | None = None,
) -> FastAPI:
    """Create an API whose writes stay local unless a token is configured."""

    device_output = output if output is not None else SimulatedDigitalOutput()
    device_mode = mode or (
        "simulated" if isinstance(device_output, SimulatedDigitalOutput) else "hardware"
    )
    write_token = token if token is not None else os.getenv("RPI_API_TOKEN")
    if idempotency_cache_size < 1:
        raise ValueError("idempotency_cache_size must be positive")
    audit_path = os.getenv("RPI_API_AUDIT_LOG")
    write_audit = audit or (AuditLog(Path(audit_path)) if audit_path else None)
    completed: OrderedDict[str, float] = OrderedDict()
    write_lock = Lock()
    if write_audit is not None:
        for entry in write_audit.read(kind="api_output_write", limit=idempotency_cache_size):
            key = entry.payload.get("idempotency_key")
            value = entry.payload.get("value")
            if (
                isinstance(key, str)
                and not isinstance(value, bool)
                and isinstance(value, (int, float))
            ):
                completed[key] = float(value)

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
            "mode": device_mode,
            "write_protection": "token" if write_token else "loopback-only",
        }

    @api.get("/output")
    def get_output() -> dict[str, float]:
        return {"value": device_output.value}

    @api.put("/output", dependencies=[Depends(require_write_access)])
    def set_output(
        command: OutputCommand,
        request: Request,
        response: Response,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, float]:
        if not 0.0 <= command.value <= 1.0:
            raise HTTPException(422, "value 必须在 0 与 1 之间")
        if idempotency_key is not None and re.fullmatch(
            r"[A-Za-z0-9._:-]{8,128}", idempotency_key
        ) is None:
            raise HTTPException(422, "Idempotency-Key 格式不正确")

        with write_lock:
            if idempotency_key is not None and idempotency_key in completed:
                original_value = completed[idempotency_key]
                if original_value != command.value:
                    raise HTTPException(409, "同一个 Idempotency-Key 不能用于不同命令")
                response.headers["Idempotency-Replayed"] = "true"
                if write_audit is not None:
                    write_audit.append(
                        "api_write_replayed",
                        request.client.host if request.client is not None else "unknown",
                        {
                            "idempotency_key": idempotency_key,
                            "requested_value": original_value,
                            "current_value": device_output.value,
                        },
                    )
                return {"value": device_output.value}

            device_output.set(command.value)
            if idempotency_key is not None:
                completed[idempotency_key] = device_output.value
                completed.move_to_end(idempotency_key)
                while len(completed) > idempotency_cache_size:
                    completed.popitem(last=False)
            if write_audit is not None:
                write_audit.append(
                    "api_output_write",
                    request.client.host if request.client is not None else "unknown",
                    {
                        "idempotency_key": idempotency_key,
                        "value": device_output.value,
                    },
                )
            return {"value": device_output.value}

    return api


app = create_app()
