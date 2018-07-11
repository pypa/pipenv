import os
import json

import requests
from flask import Flask, redirect, abort, render_template, send_file, jsonify

app = Flask(__name__)
session = requests.Session()

packages = {}


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
                pass

    def __repr__(self):
        return "<Package name={0!r} releases={1!r}".format(self.name, len(self.releases))

    def add_release(self, path_to_binary):
        path_to_binary = os.path.abspath(path_to_binary)
        path, release = os.path.split(path_to_binary)
        self.releases[release] = path_to_binary
        self._package_dirs.add(path)


def prepare_packages(path):
    """Add packages in path to the registry."""
    path = os.path.abspath(path)
    if not (os.path.exists(path) and os.path.isdir(path)):
        raise ValueError("{} is not a directory!".format(path))
    for root, dirs, files in os.walk(path):
        for file in files:
            if not file.startswith('.') and not file.endswith('.json'):
                package_name = os.path.basename(root)

                if package_name not in packages:
                    packages[package_name] = Package(package_name)

                packages[package_name].add_release(os.path.join(root, file))


@app.route('/')
def hello_world():
    return redirect('/simple', code=302)


@app.route('/simple')
def simple():
    return render_template('simple.html', packages=packages.values())


@app.route('/simple/<package>/')
def simple_package(package):
    if package in packages:
        return render_template('package.html', package=packages[package])
    else:
        abort(404)


@app.route('/<package>/<release>')
def serve_package(package, release):
    if package in packages:
        package = packages[package]

        if release in package.releases:
            return send_file(package.releases[release])

    abort(404)


@app.route('/pypi/<package>/json')
def json_for_package(package):
    try:
        return jsonify(packages[package].json)
    except Exception:
        pass

    r = session.get('https://pypi.org/pypi/{0}/json'.format(package))
    return jsonify(r.json())


if __name__ == '__main__':
    PYPI_VENDOR_DIR = os.environ.get('PYPI_VENDOR_DIR', './pypi')
    PYPI_VENDOR_DIR = os.path.abspath(PYPI_VENDOR_DIR)
    prepare_packages(PYPI_VENDOR_DIR)

    app.run()
