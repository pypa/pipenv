import os
from flask import Flask, redirect, abort, render_template, send_file

PYPI_VENDOR_DIR = os.environ.get('PYPI_VENDOR_DIR', './pypi')
PYPI_VENDOR_DIR = os.path.abspath(PYPI_VENDOR_DIR)

app = Flask(__name__)

packages = {}


class Package(object):
    """docstring for Package"""

    def __init__(self, name):
        super(Package, self).__init__()
        self.name = name
        self._releases = []

    @property
    def releases(self):
        r = []
        for release in self._releases:
            release = release[len(PYPI_VENDOR_DIR):]
            r.append(release)
        return r

    def __repr__(self):
        return "<Package name={0!r} releases={1!r}".format(self.name, len(self.releases))

    def add_release(self, path_to_binary):
        self._releases.append(path_to_binary)


def prepare_packages(path=PYPI_VENDOR_DIR):
    print(os.path.abspath(PYPI_VENDOR_DIR))
    for root, dirs, files in os.walk(os.path.abspath(PYPI_VENDOR_DIR)):
        for file in files:
            if not file.startswith('.'):
                package_name = root.split(os.path.sep)[-1]

                if package_name not in packages:
                    packages[package_name] = Package(package_name)

                packages[package_name].add_release(os.path.sep.join([root, file]))

prepare_packages()

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

        for _release in package.releases:
            if _release.endswith(release):
                return send_file(os.path.sep.join([PYPI_VENDOR_DIR, _release]))

    abort(404)

if __name__ == '__main__':
    app.run()