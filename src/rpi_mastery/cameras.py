"""Read Linux USB video inventory without opening devices or capturing frames."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class USBVideoNode:
    device: str
    name: str
    vendor_id: str
    product_id: str


def _usb_ids(device: Path) -> tuple[str, str] | None:
    resolved = device.resolve(strict=True)
    for parent in (resolved, *resolved.parents):
        try:
            vendor = (parent / "idVendor").read_text(encoding="ascii").strip()
        except FileNotFoundError:
            continue
        product = (parent / "idProduct").read_text(encoding="ascii").strip()
        if not all(re.fullmatch(r"[0-9a-fA-F]{4}", value) for value in (vendor, product)):
            raise ValueError("invalid USB vendor/product identifier")
        return vendor.lower(), product.lower()
    return None


def list_usb_video_nodes(
    sysfs_root: Path = Path("/sys/class/video4linux"),
) -> tuple[USBVideoNode, ...]:
    """Return numerically ordered USB video nodes, not a count of physical cameras.

    Missing sysfs returns no nodes (including on Windows). Other filesystem errors
    propagate: an inaccessible or disappearing device is not a successful scan.
    USB metadata nodes are included; capture capability is deliberately not claimed.
    """
    try:
        entries = list(sysfs_root.iterdir())
    except FileNotFoundError:
        return ()
    entries = [entry for entry in entries if re.fullmatch(r"video[0-9]+", entry.name)]
    nodes = []
    for entry in sorted(entries, key=lambda path: int(path.name[5:])):
        ids = _usb_ids(entry / "device")
        if ids is not None:
            name = " ".join((entry / "name").read_text(encoding="utf-8").split())
            nodes.append(USBVideoNode(f"/dev/{entry.name}", name, *ids))
    return tuple(nodes)
