from pathlib import Path

import pytest

from rpi_mastery.cameras import list_usb_video_nodes


def make_node(root: Path, number: int, vendor="0C45", product="6368"):
    node = root / f"video{number}"
    (node / "device").mkdir(parents=True)
    (node / "name").write_text("USB 摄像头\n", encoding="utf-8")
    if vendor is not None:
        (node / "device" / "idVendor").write_text(vendor, encoding="ascii")
        (node / "device" / "idProduct").write_text(product, encoding="ascii")
    return node


def test_inventory_missing_sysfs(tmp_path):
    assert list_usb_video_nodes(tmp_path / "missing") == ()


def test_inventory_sorted_and_platform_nodes_excluded(tmp_path):
    make_node(tmp_path, 10)
    make_node(tmp_path, 2)
    make_node(tmp_path, 19, vendor=None)
    (tmp_path / "not-video").mkdir()
    nodes = list_usb_video_nodes(tmp_path)
    assert [node.device for node in nodes] == ["/dev/video2", "/dev/video10"]
    assert nodes[0].name == "USB 摄像头"
    assert nodes[0].vendor_id == "0c45"
    assert nodes[0].product_id == "6368"


def test_inventory_usb_ids_on_parent(tmp_path):
    node = make_node(tmp_path, 0)
    (node / "device" / "idVendor").rename(node / "idVendor")
    (node / "device" / "idProduct").rename(node / "idProduct")
    assert list_usb_video_nodes(tmp_path)[0].vendor_id == "0c45"


@pytest.mark.parametrize("vendor", ["123", "invalid", "12345"])
def test_inventory_rejects_invalid_usb_ids(tmp_path, vendor):
    make_node(tmp_path, 0, vendor=vendor)
    with pytest.raises(ValueError, match="identifier"):
        list_usb_video_nodes(tmp_path)


def test_inventory_disappearing_device_is_error(tmp_path):
    node = make_node(tmp_path, 0)
    (node / "device").rename(node / "removed")
    with pytest.raises(FileNotFoundError):
        list_usb_video_nodes(tmp_path)


def test_inventory_missing_product_is_error(tmp_path):
    node = make_node(tmp_path, 0)
    (node / "device" / "idProduct").unlink()
    with pytest.raises(FileNotFoundError):
        list_usb_video_nodes(tmp_path)
