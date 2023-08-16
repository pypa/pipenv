import json
import os
import platform
import sys


def format_full_version(info):
    version = f"{info.major}.{info.minor}.{info.micro}"
    kind = info.releaselevel
    if kind != "final":
        version += kind[0] + str(info.serial)
    return version


# Support for 508's implementation_version.
if hasattr(sys, "implementation"):
    implementation_version = format_full_version(sys.implementation.version)
else:
    implementation_version = "0"
# Default to cpython for 2.7.
if hasattr(sys, "implementation"):
    implementation_name = sys.implementation.name
else:
    implementation_name = "cpython"
lookup = {
    "os_name": os.name,
    "sys_platform": sys.platform,
    "platform_machine": platform.machine(),
    "platform_python_implementation": platform.python_implementation(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_version": ".".join(platform.python_version().split(".")[:2]),
    "python_full_version": platform.python_version(),
    "implementation_name": implementation_name,
    "implementation_version": implementation_version,
}
if __name__ == "__main__":
    print(json.dumps(lookup))
