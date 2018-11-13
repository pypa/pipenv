# -*- coding=utf-8 -*-
import attr

from .pyenv import PyenvFinder


@attr.s
class AsdfFinder(PyenvFinder):
    version_root = attr.ib(default="installs/python/*")
