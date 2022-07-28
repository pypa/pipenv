from pipenv.vendor.dparse.parser import setuptools_parse_requirements_backport as _parse_requirements
from collections import namedtuple
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version
import pipenv.vendor.click as click
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
    if ' --hash' in line:
        line = line.split(" --hash")[0]
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

            # strip away the recursive flag
            prefixes = ["-r", "--requirement"]
            filename = line.strip()
            for prefix in prefixes:
                if filename.startswith(prefix):
                    filename = filename[len(prefix):].strip()

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


def get_proxy_dict(proxyprotocol, proxyhost, proxyport):
    proxy_dictionary = {}
    if proxyhost is not None:
        if proxyprotocol in ["http", "https"]:
            proxy_dictionary = {proxyprotocol: "{0}://{1}:{2}".format(proxyprotocol, proxyhost, str(proxyport))}
        else:
            click.secho("Proxy Protocol should be http or https only.", fg="red")
            sys.exit(-1)
    return proxy_dictionary


def get_license_name_by_id(license_id, db):
    licenses = db.get('licenses', [])
    for name, id in licenses.items():
        if id == license_id:
            return name
    return None

def get_packages_licenses(packages, licenses_db):
    """Get the licenses for the specified packages based on their version. 

    :param packages: packages list
    :param licenses_db: the licenses db in the raw form.
    :return: list of objects with the packages and their respectives licenses.
    """
    packages_licenses_db = licenses_db.get('packages', {})
    filtered_packages_licenses = []

    for pkg in packages:
        # Ignore recursive files not resolved
        if isinstance(pkg, RequirementFile):
            continue
        # normalize the package name
        pkg_name = pkg.key.replace("_", "-").lower()
        # packages may have different licenses depending their version.
        pkg_licenses = packages_licenses_db.get(pkg_name, [])
        version_requested = parse_version(pkg.version)
        license_id = None
        license_name = None
        for pkg_version in pkg_licenses:
            license_start_version = parse_version(pkg_version['start_version'])
            # Stops and return the previous stored license when a new
            # license starts on a version above the requested one.
            if version_requested >= license_start_version:
                license_id = pkg_version['license_id']
            else:
                # We found the license for the version requested
                break

        if license_id:
            license_name = get_license_name_by_id(license_id, licenses_db)
        if not license_id or not license_name:
            license_name = "N/A"

        filtered_packages_licenses.append({
            "package": pkg_name,
            "version": pkg.version,
            "license": license_name
        })

    return filtered_packages_licenses
