from dparse.parser import setuptools_parse_requirements_backport as _parse_requirements
from collections import namedtuple
import click
import sys
import json
import os
Package = namedtuple("Package", ["key", "version"])
RequirementFile = namedtuple("RequirementFile", ["path"])


def read_vulnerabilities(fh):
    return json.load(fh)


def iter_lines(fh, lineno=0):
    for line in fh.readlines()[lineno:]:
        yield line


def parse_line(line):
    if line.startswith('-e') or line.startswith('http://') or line.startswith('https://'):
        if "#egg=" in line:
            line = line.split("#egg=")[-1]
    return _parse_requirements(line)


def read_requirements(fh, resolve=False):
    """
    Reads requirements from a file like object and (optionally) from referenced files.
    :param fh: file like object to read from
    :param resolve: boolean. resolves referenced files.
    :return: generator
    """
    is_temp_file = not hasattr(fh, 'name')
    for num, line in enumerate(iter_lines(fh)):
        line = line.strip()
        if not line:
            # skip empty lines
            continue
        if line.startswith('#') or \
            line.startswith('-i') or \
            line.startswith('--index-url') or \
            line.startswith('--extra-index-url') or \
            line.startswith('-f') or line.startswith('--find-links') or \
            line.startswith('--no-index') or line.startswith('--allow-external') or \
            line.startswith('--allow-unverified') or line.startswith('-Z') or \
            line.startswith('--always-unzip'):
            # skip unsupported lines
            continue
        elif line.startswith('-r') or line.startswith('--requirement'):
            # got a referenced file here, try to resolve the path
            # if this is a tempfile, skip
            if is_temp_file:
                continue
            filename = line.strip("-r ").strip("--requirement").strip()
            # if there is a comment, remove it
            if " #" in filename:
                filename = filename.split(" #")[0].strip()
            req_file_path = os.path.join(os.path.dirname(fh.name), filename)
            if resolve:
                # recursively yield the resolved requirements
                if os.path.exists(req_file_path):
                    with open(req_file_path) as _fh:
                        for req in read_requirements(_fh, resolve=True):
                            yield req
            else:
                yield RequirementFile(path=req_file_path)
        else:
            try:
                parseable_line = line
                # multiline requirements are not parseable
                if "\\" in line:
                    parseable_line = line.replace("\\", "")
                    for next_line in iter_lines(fh, num + 1):
                        parseable_line += next_line.strip().replace("\\", "")
                        line += "\n" + next_line
                        if "\\" in next_line:
                            continue
                        break
                req, = parse_line(parseable_line)
                if len(req.specifier._specs) == 1 and \
                        next(iter(req.specifier._specs))._spec[0] == "==":
                    yield Package(key=req.name, version=next(iter(req.specifier._specs))._spec[1])
                else:
                    try:
                        fname = fh.name
                    except AttributeError:
                        fname = line

                    click.secho(
                        "Warning: unpinned requirement '{req}' found in {fname}, "
                        "unable to check.".format(req=req.name,
                                                  fname=fname),
                        fg="yellow",
                        file=sys.stderr
                    )
            except ValueError:
                continue
