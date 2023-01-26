import hashlib
import os
import sys

from functools import wraps
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version
from pathlib import Path

import pipenv.vendor.click as click

# Jinja2 will only be installed if the optional deps are installed.
# It's fine if our functions fail, but don't let this top level
# import error out.
try:
    import jinja2
except ImportError:
    jinja2 = None

import pipenv.patched.pip._vendor.requests as requests


def highest_base_score(vulns):
    highest_base_score = 0
    for vuln in vulns:
        if vuln['severity'] is not None:
            highest_base_score = max(highest_base_score, (vuln['severity'].get('cvssv3', {}) or {}).get('base_score', 10))

    return highest_base_score

def generate_branch_name(pkg, remediation):
    return pkg + "/" + remediation['recommended_version']

def generate_issue_title(pkg, remediation):
    return f"Security Vulnerability in {pkg}"

def generate_title(pkg, remediation, vulns):
    suffix = "y" if len(vulns) == 1 else "ies"
    return f"Update {pkg} from {remediation['current_version']} to {remediation['recommended_version']} to fix {len(vulns)} vulnerabilit{suffix}"

def generate_body(pkg, remediation, vulns, *, api_key):
    changelog = fetch_changelog(pkg, remediation['current_version'], remediation['recommended_version'], api_key=api_key)

    p = Path(__file__).parent / 'templates'
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(p)))
    template = env.get_template('pr.jinja2')

    overall_impact = cvss3_score_to_label(highest_base_score(vulns))
    result = template.render({"pkg": pkg, "remediation": remediation, "vulns": vulns, "changelog": changelog, "overall_impact": overall_impact, "summary_changelog": False })

    # GitHub has a PR body length limit of 65536. If we're going over that, skip the changelog and just use a link.
    if len(result) > 65500:
        return template.render({"pkg": pkg, "remediation": remediation, "vulns": vulns, "changelog": changelog, "overall_impact": overall_impact, "summary_changelog": True })

    return result

def generate_issue_body(pkg, remediation, vulns, *, api_key):
    changelog = fetch_changelog(pkg, remediation['current_version'], remediation['recommended_version'], api_key=api_key)

    p = Path(__file__).parent / 'templates'
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(Path(p)))
    template = env.get_template('issue.jinja2')

    overall_impact = cvss3_score_to_label(highest_base_score(vulns))
    result = template.render({"pkg": pkg, "remediation": remediation, "vulns": vulns, "changelog": changelog, "overall_impact": overall_impact, "summary_changelog": False })

    # GitHub has a PR body length limit of 65536. If we're going over that, skip the changelog and just use a link.
    if len(result) > 65500:
        return template.render({"pkg": pkg, "remediation": remediation, "vulns": vulns, "changelog": changelog, "overall_impact": overall_impact, "summary_changelog": True })

def generate_commit_message(pkg, remediation):
    return f"Update {pkg} from {remediation['current_version']} to {remediation['recommended_version']}"

def git_sha1(raw_contents):
    return hashlib.sha1(b"blob " + str(len(raw_contents)).encode('ascii') + b"\0" + raw_contents).hexdigest()

def fetch_changelog(package, from_version, to_version, *, api_key):
    from_version = parse_version(from_version)
    to_version = parse_version(to_version)
    changelog = {}

    r = requests.get(
        "https://pyup.io/api/v1/changelogs/{}/".format(package),
        headers={"X-Api-Key": api_key}
    )

    if r.status_code == 200:
        data = r.json()
        if data:
            # sort the changelog by release
            sorted_log = sorted(data.items(), key=lambda v: parse_version(v[0]), reverse=True)

            # go over each release and add it to the log if it's within the "upgrade
            # range" e.g. update from 1.2 to 1.3 includes a changelog for 1.2.1 but
            # not for 0.4.
            for version, log in sorted_log:
                parsed_version = parse_version(version)
                if parsed_version > from_version and parsed_version <= to_version:
                    changelog[version] = log

    return changelog

def cvss3_score_to_label(score):
    if score >= 0.1 and score <= 3.9:
        return 'low'
    elif score >= 4.0 and score <= 6.9:
        return 'medium'
    elif score >= 7.0 and score <= 8.9:
        return 'high'
    elif score >= 9.0:
        return 'critical'

    return None

def require_files_report(func):
    @wraps(func)
    def inner(obj, *args, **kwargs):
        if obj.report['report_meta']['scan_target'] != "files":
            click.secho("This report was generated against an environment, but this alerter requires a file.", fg='red')
            sys.exit(1)

        files = obj.report['report_meta']['scanned']
        obj.requirements_files = {}
        for f in files:
            if not os.path.exists(f):
                cwd = os.getcwd()
                click.secho("A requirements file scanned in the report, {}, does not exist (looking in {}).".format(f, cwd), fg='red')
                sys.exit(1)

            obj.requirements_files[f] = open(f, "rb").read()

        return func(obj, *args, **kwargs)
    return inner
