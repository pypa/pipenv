# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals
import re
import json
import tempfile
import pipenv.vendor.toml as toml
import os


class RequirementsTXTUpdater(object):

    SUB_REGEX = r"^{}(?=\s*\r?\n?$)"

    @classmethod
    def update(cls, content, dependency, version, spec="==", hashes=()):
        """
        Updates the requirement to the latest version for the given content and adds hashes
        if neccessary.
        :param content: str, content
        :return: str, updated content
        """
        new_line = "{name}{spec}{version}".format(name=dependency.full_name, spec=spec, version=version)
        appendix = ''
        # leave environment markers intact
        if ";" in dependency.line:
            # condense multiline, split out the env marker, strip comments and --hashes
            new_line += ";" + dependency.line.splitlines()[0].split(";", 1)[1] \
                .split("#")[0].split("--hash")[0].rstrip()
        # add the comment
        if "#" in dependency.line:
            # split the line into parts: requirement and comment
            parts = dependency.line.split("#")
            requirement, comment = parts[0], "#".join(parts[1:])
            # find all whitespaces between the requirement and the comment
            whitespaces = (hex(ord('\t')), hex(ord(' ')))
            trailing_whitespace = ''
            for c in requirement[::-1]:
                if hex(ord(c)) in whitespaces:
                    trailing_whitespace += c
                else:
                    break
            appendix += trailing_whitespace + "#" + comment
        # if this is a hashed requirement, add a multiline break before the comment
        if dependency.hashes and not new_line.endswith("\\"):
            new_line += " \\"
        # if this is a hashed requirement, add the hashes
        if hashes:
            for n, new_hash in enumerate(hashes):
                new_line += "\n    --hash={method}:{hash}".format(
                    method=new_hash['method'],
                    hash=new_hash['hash']
                )
                # append a new multiline break if this is not the last line
                if len(hashes) > n + 1:
                    new_line += " \\"
        new_line += appendix

        regex = cls.SUB_REGEX.format(re.escape(dependency.line))

        return re.sub(regex, new_line, content, flags=re.MULTILINE)


class CondaYMLUpdater(RequirementsTXTUpdater):

    SUB_REGEX = r"{}(?=\s*\r?\n?$)"


class ToxINIUpdater(CondaYMLUpdater):
    pass


class SetupCFGUpdater(CondaYMLUpdater):
    pass


class PipfileUpdater(object):
    @classmethod
    def update(cls, content, dependency, version, spec="==", hashes=()):
        data = toml.loads(content)
        if data:
            for package_type in ['packages', 'dev-packages']:
                if package_type in data:
                    if dependency.full_name in data[package_type]:
                        data[package_type][dependency.full_name] = "{spec}{version}".format(
                            spec=spec, version=version
                        )
        try:
            from pipenv.project import Project
        except ImportError:
            raise ImportError("Updating a Pipfile requires the pipenv extra to be installed. Install it with "
                              "pip install dparse[pipenv]")
        pipfile = tempfile.NamedTemporaryFile(delete=False)
        p = Project(chdir=False)
        p.write_toml(data=data, path=pipfile.name)
        data = open(pipfile.name).read()
        os.remove(pipfile.name)
        return data


class PipfileLockUpdater(object):
    @classmethod
    def update(cls, content, dependency, version, spec="==", hashes=()):
        data = json.loads(content)
        if data:
            for package_type in ['default', 'develop']:
                if package_type in data:
                    if dependency.full_name in data[package_type]:
                        data[package_type][dependency.full_name] = {
                            'hashes': [
                                "{method}:{hash}".format(
                                    hash=h['hash'],
                                    method=h['method']
                                ) for h in hashes
                            ],
                            'version': "{spec}{version}".format(
                                spec=spec, version=version
                            )
                        }
        return json.dumps(data, indent=4, separators=(',', ': ')) + "\n"
