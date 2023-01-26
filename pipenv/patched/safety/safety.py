# -*- coding: utf-8 -*-
import errno
import itertools
import json
import logging
import os
import sys
import time
from datetime import datetime

import pipenv.patched.pip._vendor.requests as requests
from pipenv.patched.pip._vendor.packaging.specifiers import SpecifierSet
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version, Version, LegacyVersion, parse

from .constants import (API_MIRRORS, CACHE_FILE, OPEN_MIRRORS, REQUEST_TIMEOUT, API_BASE_URL)
from .errors import (DatabaseFetchError, DatabaseFileNotFoundError,
                     InvalidKeyError, TooManyRequestsError, NetworkConnectionError,
                     RequestTimeoutError, ServerError, MalformedDatabase)
from .models import Vulnerability, CVE, Severity
from .util import RequirementFile, read_requirements, Package, build_telemetry_data, sync_safety_context, SafetyContext, \
    validate_expiration_date, is_a_remote_mirror

session = requests.session()

LOG = logging.getLogger(__name__)


def get_from_cache(db_name, cache_valid_seconds=0):
    LOG.debug('Trying to get from cache...')
    if os.path.exists(CACHE_FILE):
        LOG.info('Cache file path: %s', CACHE_FILE)
        with open(CACHE_FILE) as f:
            try:
                data = json.loads(f.read())
                LOG.debug('Trying to get the %s from the cache file', db_name)
                LOG.debug('Databases in CACHE file: %s', ', '.join(data))
                if db_name in data:
                    LOG.debug('db_name %s', db_name)

                    if "cached_at" in data[db_name]:
                        if data[db_name]["cached_at"] + cache_valid_seconds > time.time():
                            LOG.debug('Getting the database from cache at %s, cache setting: %s',
                                      data[db_name]["cached_at"], cache_valid_seconds)
                            return data[db_name]["db"]

                        LOG.debug('Cached file is too old, it was cached at %s', data[db_name]["cached_at"])
                    else:
                        LOG.debug('There is not the cached_at key in %s database', data[db_name])

            except json.JSONDecodeError:
                LOG.debug('JSONDecodeError trying to get the cached database.')
    else:
        LOG.debug("Cache file doesn't exist...")
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
                LOG.debug('Cache file created')
        except OSError as exc:  # Guard against race condition
            LOG.debug('Unable to create the cache file because: %s', exc.errno)
            if exc.errno != errno.EEXIST:
                raise

    with open(CACHE_FILE, "r") as f:
        try:
            cache = json.loads(f.read())
        except json.JSONDecodeError:
            LOG.debug('JSONDecodeError in the local cache, dumping the full cache file.')
            cache = {}

    with open(CACHE_FILE, "w") as f:
        cache[db_name] = {
            "cached_at": time.time(),
            "db": data
        }
        f.write(json.dumps(cache))
        LOG.debug('Safety updated the cache file for %s database.', db_name)


def fetch_database_url(mirror, db_name, key, cached, proxy, telemetry=True):
    headers = {}
    if key:
        headers["X-Api-Key"] = key

    if not proxy:
        proxy = {}

    if cached:
        cached_data = get_from_cache(db_name=db_name, cache_valid_seconds=cached)
        if cached_data:
            LOG.info('Database %s returned from cache.', db_name)
            return cached_data
    url = mirror + db_name

    telemetry_data = {'telemetry': json.dumps(build_telemetry_data(telemetry=telemetry))}

    try:
        r = session.get(url=url, timeout=REQUEST_TIMEOUT, headers=headers, proxies=proxy, params=telemetry_data)
    except requests.exceptions.ConnectionError:
        raise NetworkConnectionError()
    except requests.exceptions.Timeout:
        raise RequestTimeoutError()
    except requests.exceptions.RequestException:
        raise DatabaseFetchError()

    if r.status_code == 403:
        raise InvalidKeyError(key=key, reason=r.text)

    if r.status_code == 429:
        raise TooManyRequestsError(reason=r.text)

    if r.status_code != 200:
        raise ServerError(reason=r.reason)

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise MalformedDatabase(reason=e)

    if cached:
        LOG.info('Writing %s to cache because cached value was %s', db_name, cached)
        write_to_cache(db_name, data)

    return data


def fetch_policy(key, proxy):
    url = f"{API_BASE_URL}policy/"
    headers = {"X-Api-Key": key}

    if not proxy:
        proxy = {}

    try:
        LOG.debug(f'Getting policy')
        r = session.get(url=url, timeout=REQUEST_TIMEOUT, headers=headers, proxies=proxy)
        LOG.debug(r.text)
        return r.json()
    except:
        import pipenv.vendor.click as click

        LOG.exception("Error fetching policy")
        click.secho(
            "Warning: couldn't fetch policy from pyup.io.",
            fg="yellow",
            file=sys.stderr
        )

        return {"safety_policy": "", "audit_and_monitor": False}


def post_results(key, proxy, safety_json, policy_file):
    url = f"{API_BASE_URL}result/"
    headers = {"X-Api-Key": key}

    if not proxy:
        proxy = {}

    # safety_json is in text form already. policy_file is a text YAML
    audit_report = {
        "safety_json": json.loads(safety_json),
        "policy_file": policy_file
    }

    try:
        LOG.debug(f'Posting results: {audit_report}')
        r = session.post(url=url, timeout=REQUEST_TIMEOUT, headers=headers, proxies=proxy, json=audit_report)
        LOG.debug(r.text)

        return r.json()
    except:
        import pipenv.vendor.click as click

        LOG.exception("Error posting results")
        click.secho(
            "Warning: couldn't upload results to pyup.io.",
            fg="yellow",
            file=sys.stderr
        )

        return {}


def fetch_database_file(path, db_name):
    full_path = os.path.join(path, db_name)
    if not os.path.exists(full_path):
        raise DatabaseFileNotFoundError(db=path)
    with open(full_path) as f:
        return json.loads(f.read())


def fetch_database(full=False, key=False, db=False, cached=0, proxy=None, telemetry=True):
    if key:
        mirrors = API_MIRRORS
    elif db:
        mirrors = [db]
    else:
        mirrors = OPEN_MIRRORS

    db_name = "insecure_full.json" if full else "insecure.json"
    for mirror in mirrors:
        # mirror can either be a local path or a URL
        if is_a_remote_mirror(mirror):
            data = fetch_database_url(mirror, db_name=db_name, key=key, cached=cached, proxy=proxy, telemetry=telemetry)
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


def get_vulnerability_from(vuln_id, cve, data, specifier, db, name, pkg, ignore_vulns):
    base_domain = db.get('$meta', {}).get('base_domain')
    pkg_meta = db.get('$meta', {}).get('packages', {}).get(name, {})
    insecure_versions = pkg_meta.get("insecure_versions", [])
    secure_versions = pkg_meta.get("secure_versions", [])
    latest_version_without_known_vulnerabilities = pkg_meta.get("latest_secure_version", None)
    latest_version = pkg_meta.get("latest_version", None)
    pkg_refreshed = pkg._replace(insecure_versions=insecure_versions, secure_versions=secure_versions,
                                 latest_version_without_known_vulnerabilities=latest_version_without_known_vulnerabilities,
                                 latest_version=latest_version,
                                 more_info_url=f"{base_domain}{pkg_meta.get('more_info_path', '')}")

    ignored = (ignore_vulns and vuln_id in ignore_vulns and (
            not ignore_vulns[vuln_id]['expires'] or ignore_vulns[vuln_id]['expires'] > datetime.utcnow()))
    more_info_url = f"{base_domain}{data.get('more_info_path', '')}"
    severity = None

    if cve and (cve.cvssv2 or cve.cvssv3):
        severity = Severity(source=cve.name, cvssv2=cve.cvssv2, cvssv3=cve.cvssv3)

    return Vulnerability(
        vulnerability_id=vuln_id,
        package_name=name,
        pkg=pkg_refreshed,
        ignored=ignored,
        ignored_reason=ignore_vulns.get(vuln_id, {}).get('reason', None) if ignore_vulns else None,
        ignored_expires=ignore_vulns.get(vuln_id, {}).get('expires', None) if ignore_vulns else None,
        vulnerable_spec=specifier,
        all_vulnerable_specs=data.get("specs", []),
        analyzed_version=pkg_refreshed.version,
        advisory=data.get("advisory"),
        is_transitive=data.get("transitive", False),
        published_date=data.get("published_date"),
        fixed_versions=[ver for ver in data.get("fixed_versions", []) if ver],
        closest_versions_without_known_vulnerabilities=data.get("closest_secure_versions", []),
        resources=data.get("vulnerability_resources"),
        CVE=cve,
        severity=severity,
        affected_versions=data.get("affected_versions", []),
        more_info_url=more_info_url
    )


def get_cve_from(data, db_full):
    cve_data = data.get("cve", '')

    if not cve_data:
        return None

    cve_id = cve_data.split(",")[0].strip()
    cve_meta = db_full.get("$meta", {}).get("cve", {}).get(cve_id, {})
    return CVE(name=cve_id, cvssv2=cve_meta.get("cvssv2", None),
               cvssv3=cve_meta.get("cvssv3", None))


def ignore_vuln_if_needed(vuln_id, cve, ignore_vulns, ignore_severity_rules):

    if not ignore_severity_rules or not isinstance(ignore_vulns, dict):
        return

    severity = None

    if cve:
        if cve.cvssv2 and cve.cvssv2.get("base_score", None):
            severity = cve.cvssv2.get("base_score", None)

        if cve.cvssv3 and cve.cvssv3.get("base_score", None):
            severity = cve.cvssv3.get("base_score", None)

    ignore_severity_below = float(ignore_severity_rules.get('ignore-cvss-severity-below', 0.0))
    ignore_unknown_severity = bool(ignore_severity_rules.get('ignore-cvss-unknown-severity', False))

    if severity:
        if float(severity) < ignore_severity_below:
            reason = 'Ignored by severity rule in policy file, {0} < {1}'.format(float(severity),
                                                                                  ignore_severity_below)
            ignore_vulns[vuln_id] = {'reason': reason, 'expires': None}
    elif ignore_unknown_severity:
        reason = 'Unknown CVSS severity, ignored by severity rule in policy file.'
        ignore_vulns[vuln_id] = {'reason': reason, 'expires': None}


@sync_safety_context
def check(packages, key=False, db_mirror=False, cached=0, ignore_vulns=None, ignore_severity_rules=None, proxy=None,
          include_ignored=False, is_env_scan=True, telemetry=True, params=None, project=None):
    SafetyContext().command = 'check'
    db = fetch_database(key=key, db=db_mirror, cached=cached, proxy=proxy, telemetry=telemetry)
    db_full = None
    vulnerable_packages = frozenset(db.keys())
    vulnerabilities = []

    for pkg in packages:
        # Ignore recursive files not resolved
        if isinstance(pkg, RequirementFile):
            continue

        # normalize the package name, the safety-db is converting underscores to dashes and uses
        # lowercase
        name = canonicalize_name(pkg.name)

        if name in vulnerable_packages:
            # we have a candidate here, build the spec set
            for specifier in db[name]:
                spec_set = SpecifierSet(specifiers=specifier)
                if spec_set.contains(pkg.version):
                    if not db_full:
                        db_full = fetch_database(full=True, key=key, db=db_mirror, cached=cached, proxy=proxy,
                                                 telemetry=telemetry)
                    for data in get_vulnerabilities(pkg=name, spec=specifier, db=db_full):
                        vuln_id = data.get("id").replace("pyup.io-", "")
                        cve = get_cve_from(data, db_full)

                        ignore_vuln_if_needed(vuln_id, cve, ignore_vulns, ignore_severity_rules)

                        vulnerability = get_vulnerability_from(vuln_id, cve, data, specifier, db_full, name, pkg,
                                                               ignore_vulns)

                        should_add_vuln = not (vulnerability.is_transitive and is_env_scan)

                        if (include_ignored or vulnerability.vulnerability_id not in ignore_vulns) and should_add_vuln:
                            vulnerabilities.append(vulnerability)

    return vulnerabilities, db_full


def precompute_remediations(remediations, package_metadata, vulns,
                            ignored_vulns):
    for vuln in vulns:
        if vuln.ignored:
            ignored_vulns.add(vuln.vulnerability_id)
            continue

        if vuln.package_name in remediations.keys():
            remediations[vuln.package_name]['vulns_found'] = remediations[vuln.package_name].get('vulns_found', 0) + 1
        else:
            vulns_count = 1
            package_metadata[vuln.package_name] = {'insecure_versions': vuln.pkg.insecure_versions,
                                           'secure_versions': vuln.pkg.secure_versions, 'version': vuln.pkg.version}
            remediations[vuln.package_name] = {'vulns_found': vulns_count, 'version': vuln.pkg.version,
                                               'more_info_url': vuln.pkg.more_info_url}


def get_closest_ver(versions, version):
    results = {'minor': None, 'major': None}
    if not version or not versions:
        return results

    sorted_versions = sorted(versions, key=lambda ver: parse_version(ver), reverse=True)

    for v in sorted_versions:
        index = parse_version(v)
        current_v = parse_version(version)

        if index > current_v:
            results['major'] = index

        if index < current_v:
            results['minor'] = index
            break

    return results


def compute_sec_ver_for_user(package, ignored_vulns, db_full):
    pkg_meta = db_full.get('$meta', {}).get('packages', {}).get(package, {})
    versions = set(pkg_meta.get("insecure_versions", []) + pkg_meta.get("secure_versions", []))
    affected_versions = []

    for vuln in db_full.get(package, []):
        vuln_id = vuln.get('id', None)
        if vuln_id and vuln_id not in ignored_vulns:
            affected_versions += vuln.get('affected_versions', [])

    affected_v = set(affected_versions)
    sec_ver_for_user = list(versions.difference(affected_v))

    return sorted(sec_ver_for_user, key=lambda ver: parse_version(ver), reverse=True)


def compute_sec_ver(remediations, package_metadata, ignored_vulns, db_full):
    """
    Compute the secure_versions and the closest_secure_version for each remediation using the affected_versions
    of each no ignored vulnerability of the same package, there is only a remediation for each package.
    """
    for pkg_name in remediations.keys():
        pkg = package_metadata.get(pkg_name, {})

        if not ignored_vulns:
            secure_v = pkg.get('secure_versions', [])
        else:
            secure_v = compute_sec_ver_for_user(package=pkg_name, ignored_vulns=ignored_vulns, db_full=db_full)

        remediations[pkg_name]['secure_versions'] = secure_v
        remediations[pkg_name]['closest_secure_version'] = get_closest_ver(secure_v,
                                                                           pkg.get('version', None))


def calculate_remediations(vulns, db_full):
    remediations = {}
    package_metadata = {}
    ignored_vulns = set()

    if not db_full:
        return remediations

    precompute_remediations(remediations, package_metadata, vulns, ignored_vulns)
    compute_sec_ver(remediations, package_metadata, ignored_vulns, db_full)

    return remediations


@sync_safety_context
def review(report=None, params=None):
    SafetyContext().command = 'review'
    vulnerable = []
    vulnerabilities = report.get('vulnerabilities', []) + report.get('ignored_vulnerabilities', [])
    remediations = {}

    for key, value in report.get('remediations', {}).items():
        recommended = value.get('recommended_version', None)
        secure_v = value.get('other_recommended_versions', [])
        major = None
        if recommended:
            secure_v.append(recommended)
            major = parse(recommended)

        remediations[key] = {'vulns_found': value.get('vulnerabilities_found', 0),
                             'version': value.get('current_version'),
                             'secure_versions': secure_v,
                             'closest_secure_version': {'major': major, 'minor': None},
                             # minor isn't supported in review
                             'more_info_url': value.get('more_info_url')}

    packages = report.get('scanned_packages', [])
    pkgs = {pkg_name: Package(**pkg_values) for pkg_name, pkg_values in packages.items()}
    ctx = SafetyContext()
    found_packages = list(pkgs.values())
    ctx.packages = found_packages
    ctx.review = report.get('report_meta', [])
    ctx.key = ctx.review.get('api_key', False)
    cvssv2 = None
    cvssv3 = None

    for vuln in vulnerabilities:
        vuln['pkg'] = pkgs.get(vuln.get('package_name', None))
        XVE_ID = vuln.get('CVE', None)  # Trying to get first the CVE ID

        severity = vuln.get('severity', None)
        if severity and severity.get('source', False):
            cvssv2 = severity.get('cvssv2', None)
            cvssv3 = severity.get('cvssv3', None)
            # Trying to get the PVE ID if it exists, otherwise it will be the same CVE ID of above
            XVE_ID = severity.get('source', False)
            vuln['severity'] = Severity(source=XVE_ID, cvssv2=cvssv2, cvssv3=cvssv3)
        else:
            vuln['severity'] = None

        ignored_expires = vuln.get('ignored_expires', None)

        if ignored_expires:
            vuln['ignored_expires'] = validate_expiration_date(ignored_expires)

        vuln['CVE'] = CVE(name=XVE_ID, cvssv2=cvssv2, cvssv3=cvssv3) if XVE_ID else None

        vulnerable.append(Vulnerability(**vuln))

    return vulnerable, remediations, found_packages


@sync_safety_context
def get_licenses(key=False, db_mirror=False, cached=0, proxy=None, telemetry=True):
    key = key if key else os.environ.get("SAFETY_API_KEY", False)

    if not key and not db_mirror:
        raise InvalidKeyError(message="The API-KEY was not provided.")
    if db_mirror:
        mirrors = [db_mirror]
    else:
        mirrors = API_MIRRORS

    db_name = "licenses.json"

    for mirror in mirrors:
        # mirror can either be a local path or a URL
        if is_a_remote_mirror(mirror):
            licenses = fetch_database_url(mirror, db_name=db_name, key=key, cached=cached, proxy=proxy,
                                          telemetry=telemetry)
        else:
            licenses = fetch_database_file(mirror, db_name=db_name)
        if licenses:
            return licenses
    raise DatabaseFetchError()


def get_announcements(key, proxy, telemetry=True):
    LOG.info('Getting announcements')

    announcements = []
    headers = {}

    if key:
        headers["X-Api-Key"] = key

    url = f"{API_BASE_URL}announcements/"
    method = 'post'
    data = build_telemetry_data(telemetry=telemetry)
    request_kwargs = {'headers': headers, 'proxies': proxy, 'timeout': 3}
    data_keyword = 'json'

    source = os.environ.get('SAFETY_ANNOUNCEMENTS_URL', None)

    if source:
        LOG.debug(f'Getting the announcement from a different source: {source}')
        url = source
        method = 'get'
        data = {
            'telemetry': json.dumps(data)}
        data_keyword = 'params'

    request_kwargs[data_keyword] = data
    request_kwargs['url'] = url

    LOG.debug(f'Telemetry data sent: {data}')

    try:
        request_func = getattr(session, method)
        r = request_func(**request_kwargs)
        LOG.debug(r.text)
    except Exception as e:
        LOG.info('Unexpected but HANDLED Exception happened getting the announcements: %s', e)
        return announcements

    if r.status_code == 200:
        try:
            announcements = r.json()
            if 'announcements' in announcements.keys():
                announcements = announcements.get('announcements', [])
            else:
                LOG.info('There is not announcements key in the JSON response, is this a wrong structure?')
                announcements = []

        except json.JSONDecodeError as e:
            LOG.info('Unexpected but HANDLED Exception happened decoding the announcement response: %s', e)

    LOG.info('Announcements fetched')

    return announcements


def get_packages(files=False, stdin=False):

    if files:
        return list(itertools.chain.from_iterable(read_requirements(f, resolve=True) for f in files))

    if stdin:
        return list(read_requirements(sys.stdin))

    import pipenv.patched.pip._vendor.pkg_resources as pkg_resources

    return [
        Package(name=d.key, version=d.version, found=d.location, insecure_versions=[], secure_versions=[],
                latest_version=None, latest_version_without_known_vulnerabilities=None, more_info_url=None) for d in
        pkg_resources.working_set
        if d.key not in {"python", "wsgiref", "argparse"}
    ]


def read_vulnerabilities(fh):
    try:
        data = json.load(fh)
    except json.JSONDecodeError as e:
        raise MalformedDatabase(reason=e, fetched_from=fh.name)
    except TypeError as e:
        raise MalformedDatabase(reason=e, fetched_from=fh.name)

    return data


def close_session():
    LOG.debug('Closing requests session.')
    session.close()
