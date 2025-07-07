# -*- coding: utf-8 -*-

import re

__version__ = "0.0.1a1.dev1"


_VersionInfo = __import__("collections").namedtuple(
    "version_info", ["major", "minor", "micro"]
)

# 用正则提取主、次、修订号
match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", __version__)
major = int(match.group(1)) if match and match.group(1) else 0
minor = int(match.group(2)) if match and match.group(2) else 0
micro = int(match.group(3)) if match and match.group(3) else 0

version_info = _VersionInfo(major, minor, micro)

version_str = "qmdatasdk version {}, python version {}".format(
    __version__,
    ".".join(str(item) for item in __import__("sys").version_info)
)
