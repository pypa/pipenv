# -*- coding: utf-8 -*-
 json
 os
 platform
 sys


 format_full_version(info):
    version  "{0.major}.{0.minor}.{0.micro}".format(info)
    kind  info.releaselevel
     kind  "final":
        version  kind[]  str(info.serial)
     version


# Support for 508's implementation_version.
hasattr(sys, "implementation"):
    implementation_version  format_full_version(sys.implementation.version)
    :
    implementation_version  "0"
# Default  cpython  2.7.
 hasattr(sys, "implementation"):
    implementation_name  sys.implementation.name
    :
    implementation_name  "cpython"
lookup  {
    "os_name": os.name,
    "sys_platform": sys.platform,
    "platform_machine": platform.machine(),
    "platform_python_implementation": platform.python_implementation(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_version": ".".join(platform.python_version().split(".")[ ]),
    "python_full_version": platform.python_version(),
    "implementation_name": implementation_name,
    "implementation_version": implementation_version,
}
 __name__   "__main__":
     (json.dumps(lookup))
