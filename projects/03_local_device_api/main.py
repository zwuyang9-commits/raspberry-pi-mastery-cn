from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from rpi_mastery.hardware import SimulatedDigitalOutput

app = FastAPI(title="树莓派本地设备 API", version="1.0")
output = SimulatedDigitalOutput()


class OutputCommand(BaseModel):
    value: float


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": "simulated"}


@app.get("/output")
def get_output() -> dict:
    return {"value": output.value}


@app.put("/output")
def set_output(command: OutputCommand) -> dict:
    if not 0.0 <= command.value <= 1.0:
        raise HTTPException(422, "value 必须在 0 与 1 之间")
    output.set(command.value)
    return {"value": output.value}
