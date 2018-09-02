# -*- coding: utf-8 -*-
import attr

from packaging.markers import InvalidMarker, Marker

from ..exceptions import RequirementError
from .baserequirement import BaseRequirement
from .utils import filter_none, validate_markers


@attr.s
class PipenvMarkers(BaseRequirement):
    """System-level requirements - see PEP508 for more detail"""

    os_name = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    sys_platform = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_machine = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_python_implementation = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_release = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_system = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    platform_version = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    python_version = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    python_full_version = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    implementation_name = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )
    implementation_version = attr.ib(
        default=None, validator=attr.validators.optional(validate_markers)
    )

    @property
    def line_part(self):
        return " and ".join(
            [
                "{0} {1}".format(k, v)
                for k, v in attr.asdict(self, filter=filter_none).items()
            ]
        )

    @property
    def pipfile_part(self):
        return {"markers": self.as_line}

    @classmethod
    def make_marker(cls, marker_string):
        try:
            marker = Marker(marker_string)
        except InvalidMarker:
            raise RequirementError(
                "Invalid requirement: Invalid marker %r" % marker_string
            )
        return marker

    @classmethod
    def from_line(cls, line):
        if ";" in line:
            line = line.rsplit(";", 1)[1].strip()
        marker = cls.make_marker(line)
        return marker

    @classmethod
    def from_pipfile(cls, name, pipfile):
        found_keys = [k for k in pipfile.keys() if k in cls.attr_fields()]
        marker_strings = ["{0} {1}".format(k, pipfile[k]) for k in found_keys]
        if pipfile.get("markers"):
            marker_strings.append(pipfile.get("markers"))
        markers = set()
        for marker in marker_strings:
            markers.add(marker)
        combined_marker = None
        try:
            combined_marker = cls.make_marker(" and ".join(sorted(markers)))
        except RequirementError:
            pass
        else:
            return combined_marker
