"""List USB video nodes as JSON; never capture or upload frames."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from rpi_mastery.cameras import list_usb_video_nodes


def main() -> int:
    root = Path("/sys/class/video4linux")
    try:
        nodes = list_usb_video_nodes(root)
        print(
            json.dumps(
                {
                    "sysfs_available": root.is_dir(),
                    "capture_tested": False,
                    "nodes": [asdict(node) for node in nodes],
                },
                ensure_ascii=False,
            )
        )
    except (OSError, ValueError) as error:
        print(f"USB video inventory failed: {' '.join(str(error).splitlines())}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
