"""采集器分派：按当前平台暴露 office / onedrive / environment / device 实现。

oneauth 与 edge 两个采集器跨平台共享（同一套 Chromium / OneAuth 存储），
其余四类存储差异较大，各自提供 *_mac / *_win 实现，导出接口保持一致：

    collect() -> dict
"""

from .._platform import IS_MACOS

if IS_MACOS:
    from . import device_mac as device
    from . import environment_mac as environment
    from . import office_mac as office
    from . import onedrive_mac as onedrive
else:
    from . import device_win as device
    from . import environment_win as environment
    from . import office_win as office
    from . import onedrive_win as onedrive

__all__ = ["device", "edge", "environment", "office", "oneauth", "onedrive"]
