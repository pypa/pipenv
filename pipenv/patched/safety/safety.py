# -*- coding: utf-8 -*-
import requests
from packaging.specifiers import SpecifierSet
from .errors import DatabaseFetchError, InvalidKeyError, DatabaseFileNotFoundError
from .constants import OPEN_MIRRORS, API_MIRRORS, REQUEST_TIMEOUT, CACHE_VALID_SECONDS, CACHE_FILE
from collections import namedtuple
import os
import json
import time
import errno


class Vulnerability(namedtuple("Vulnerability",
                               ["name", "spec", "version", "advisory", "vuln_id"])):
    pass


def get_from_cache(db_name):
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            try:
                data = json.loads(f.read())
                if db_name in data:
                    if "cached_at" in data[db_name]:
                        if data[db_name]["cached_at"] + CACHE_VALID_SECONDS > time.time():
                            return data[db_name]["db"]
            except json.JSONDecodeError:
                pass
    return False


def write_to_cache(db_name, data):
    # cache is in: ~/safety/cache.json
    # and has the following form:
    # {
    #   "insecure.json": {
    #       "cached_at": 12345678
    #       "db": {}
    #   },
    #   "insecure_full.json": {
    #       "cached_at": 12345678
    #       "db": {}
    #   },
    # }
    if not os.path.exists(os.path.dirname(CACHE_FILE)):
        try:
            os.makedirs(os.path.dirname(CACHE_FILE))
            with open(CACHE_FILE, "w") as _:
                _.write(json.dumps({}))
        except OSError as exc:  # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

    with open(CACHE_FILE, "r") as f:
        try:
            cache = json.loads(f.read())
        except json.JSONDecodeError:
            cache = {}

    with open(CACHE_FILE, "w") as f:
        cache[db_name] = {
            "cached_at": time.time(),
            "db": data
        }
        f.write(json.dumps(cache))


def fetch_database_url(mirror, db_name, key, cached, proxy):

    headers = {}
    if key:
        headers["X-Api-Key"] = key

    if cached:
        cached_data = get_from_cache(db_name=db_name)
        if cached_data:
            return cached_data
    url = mirror + db_name
    r = requests.get(url=url, timeout=REQUEST_TIMEOUT, headers=headers, proxies=proxy)
    if r.status_code == 200:
        data = r.json()
        if cached:
            write_to_cache(db_name, data)
        return data
    elif r.status_code == 403:
        raise InvalidKeyError()


def fetch_database_file(path, db_name):
    full_path = os.path.join(path, db_name)
    if not os.path.exists(full_path):
        raise DatabaseFileNotFoundError()
    with open(full_path) as f:
        return json.loads(f.read())


def fetch_database(full=False, key=False, db=False, cached=False, proxy={}):

    if db:
        mirrors = [db]
    else:
        mirrors = API_MIRRORS if key else OPEN_MIRRORS

    db_name = "insecure_full.json" if full else "insecure.json"
    for mirror in mirrors:
        # mirror can either be a local path or a URL
        if mirror.startswith("http://") or mirror.startswith("https://"):
            data = fetch_database_url(mirror, db_name=db_name, key=key, cached=cached, proxy=proxy)
        else:
            data = fetch_database_file(mirror, db_name=db_name)
        if data:
            return data
    raise DatabaseFetchError()


def get_vulnerabilities(pkg, spec, db):
    for entry in db[pkg]:
        for entry_spec in entry["specs"]:
            if entry_spec == spec:
                yield entry


def check(packages, key, db_mirror, cached, ignore_ids, proxy):
    key = key if key else os.environ.get("SAFETY_API_KEY", False)
    db = fetch_database(key=key, db=db_mirror, cached=cached, proxy=proxy)
    db_full = None
    vulnerable_packages = frozenset(db.keys())
    vulnerable = []
    for pkg in packages:
        # normalize the package name, the safety-db is converting underscores to dashes and uses
        # lowercase
        name = pkg.key.replace("_", "-").lower()

        if name in vulnerable_packages:
            # we have a candidate here, build the spec set
            for specifier in db[name]:
                spec_set = SpecifierSet(specifiers=specifier)
                if spec_set.contains(pkg.version):
                    if not db_full:
                        db_full = fetch_database(full=True, key=key, db=db_mirror, cached=cached, proxy=proxy)
                    for data in get_vulnerabilities(pkg=name, spec=specifier, db=db_full):
                        vuln_id = data.get("id").replace("pyup.io-", "")
                        if vuln_id and vuln_id not in ignore_ids:
                            vulnerable.append(
                                Vulnerability(
                                    name=name,
                                    spec=specifier,
                                    version=pkg.version,
                                    advisory=data.get("advisory"),
                                    vuln_id=vuln_id
                                )
                            )
    return vulnerable


def review(vulnerabilities):
    vulnerable = []
    for vuln in vulnerabilities:
        current_vuln = {
            "name": vuln[0],
            "spec": vuln[1],
            "version": vuln[2],
            "advisory": vuln[3],
            "vuln_id": vuln[4],
        }
        vulnerable.append(
            Vulnerability(**current_vuln)
        )
    return vulnerable
