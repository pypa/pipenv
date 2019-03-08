import os
import json
import io
import sys

import requests
from flask import Flask, redirect, abort, render_template, send_file, jsonify
from zipfile import is_zipfile
from tarfile import is_tarfile

app = Flask(__name__)
session = requests.Session()

packages = {}
ARTIFACTS = {}

class Package(object):
    """Package represents a collection of releases from one or more directories"""

    def __init__(self, name):
        super(Package, self).__init__()
        self.name = name
        self.releases = {}
        self._package_dirs = set()

    @property
    def json(self):
        for path in self._package_dirs:
            try:
                with open(os.path.join(path, 'api.json')) as f:
                    return json.load(f)
            except FileNotFoundError:
                r = session.get('https://pypi.org/pypi/{0}/json'.format(self.name))
                response = r.json()
                releases = response["releases"]
                files = {
                    pkg for pkg_dir in self._package_dirs
                    for pkg in os.listdir(pkg_dir)
                }
                for release in list(releases.keys()):
                    values = (
                        r for r in releases[release] if r["filename"] in files
                    )
                    values = list(values)
                    if values:
                        releases[release] = values
                    else:
                        del releases[release]
                response["releases"] = releases
                with io.open(os.path.join(path, "api.json"), "w") as fh:
                    json.dump(response, fh, indent=4)
                return response

    def __repr__(self):
        return "<Package name={0!r} releases={1!r}".format(self.name, len(self.releases))

    def add_release(self, path_to_binary):
        path_to_binary = os.path.abspath(path_to_binary)
        path, release = os.path.split(path_to_binary)
        self.releases[release] = path_to_binary
        self._package_dirs.add(path)


class Artifact(object):
    """Represents an artifact for download"""

    def __init__(self, name):
        super(Artifact, self).__init__()
        self.name = name
        self.files = {}
        self._artifact_dirs = set()

    def __repr__(self):
        return "<Artifact name={0!r} files={1!r}".format(self.name, len(self.files))

    def add_file(self, path):
        path = os.path.abspath(path)
        base_path, fn = os.path.split(path)
        self.files[fn] = path
        self._artifact_dirs.add(base_path)


def prepare_fixtures(path):
    path = os.path.abspath(path)
    if not (os.path.exists(path) and os.path.isdir(path)):
        raise ValueError("{} is not a directory!".format(path))
    for root, dirs, files in os.walk(path):
        package_name, _, _ = os.path.relpath(root, start=path).partition(os.path.sep)
        if package_name not in ARTIFACTS:
            ARTIFACTS[package_name] = Artifact(package_name)
        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, start=path)
            _, _, subpkg = rel_path.partition(os.path.sep)
            subpkg, _, _ = subpkg.partition(os.path.sep)
            pkg, ext = os.path.splitext(subpkg)
            if not (is_tarfile(file_path) or is_zipfile(file_path) or ext == ".git"):
                continue
            if subpkg not in ARTIFACTS[package_name].files:
                ARTIFACTS[package_name].add_file(os.path.join(root, file))
            ARTIFACTS[package_name].add_file(os.path.join(root, file))


def prepare_packages(path):
    """Add packages in path to the registry."""
    path = os.path.abspath(path)
    if not (os.path.exists(path) and os.path.isdir(path)):
        raise ValueError("{} is not a directory!".format(path))
    for root, dirs, files in os.walk(path):
        for file in files:
            if not file.startswith('.') and not file.endswith('.json'):
                package_name = os.path.basename(root)
                if package_name and package_name == "fixtures":
                    prepare_fixtures(root)
                    continue
                if package_name not in packages:
                    packages[package_name] = Package(package_name)

                packages[package_name].add_release(os.path.join(root, file))


@app.route('/')
def hello_world():
    return redirect('/simple', code=302)


@app.route('/simple')
def simple():
    return render_template('simple.html', packages=packages.values())


@app.route('/artifacts')
def artifacts():
    return render_template('artifacts.html', artifacts=ARTIFACTS.values())


@app.route('/simple/<package>/')
def simple_package(package):
    if package in packages:
        return render_template('package.html', package=packages[package])
    else:
        abort(404)


@app.route('/artifacts/<artifact>/')
def simple_artifact(artifact):
    if artifact in ARTIFACTS:
        return render_template('artifact.html', artifact=ARTIFACTS[artifact])
    else:
        abort(404)


@app.route('/<package>/<release>')
def serve_package(package, release):
    if package in packages:
        package = packages[package]

        if release in package.releases:
            return send_file(package.releases[release])

    abort(404)


@app.route('/artifacts/<artifact>/<fn>')
def serve_artifact(artifact, fn):
    if artifact in ARTIFACTS:
        artifact = ARTIFACTS[artifact]
        if fn in artifact.files:
            return send_file(artifact.files[fn])
    abort(404)


@app.route('/pypi/<package>/json')
def json_for_package(package):
    return jsonify(packages[package].json)
    # try:
    # except Exception:
    #     r = session.get('https://pypi.org/pypi/{0}/json'.format(package))
    #     return jsonify(r.json())


if __name__ == '__main__':
    PYPI_VENDOR_DIR = os.environ.get('PYPI_VENDOR_DIR', './pypi')
    PYPI_VENDOR_DIR = os.path.abspath(PYPI_VENDOR_DIR)
    prepare_packages(PYPI_VENDOR_DIR)
    prepare_fixtures(os.path.join(PYPI_VENDOR_DIR, "fixtures"))

    app.run()
