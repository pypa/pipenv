# -*- coding: utf-8 -*-
import platform
import sys
import json
import os
import textwrap

from .util import get_packages_licenses

# python 2.7 compat
try:
    FileNotFoundError
except NameError:
    FileNotFoundError = IOError

try:
    system = platform.system()
    python_version = ".".join([str(i) for i in sys.version_info[0:2]])
    # get_terminal_size exists on Python 3.4 but isn't working on windows
    if system == "Windows" and python_version in ["3.4"]:
        raise ImportError
    from shutil import get_terminal_size
except ImportError:
    # fallback for python < 3
    import subprocess
    from collections import namedtuple

    def get_terminal_size():
        size = namedtuple("_", ["rows", "columns"])
        try:
            rows, columns = subprocess.check_output(
                ['stty', 'size'],
                stderr=subprocess.STDOUT
            ).split()
            return size(rows=int(rows), columns=int(columns))
        # this won't work
        # - on windows (FileNotFoundError/OSError)
        # - python 2.6 (AttributeError)
        # - if the output is somehow mangled (ValueError)
        except (ValueError, FileNotFoundError, OSError,
                AttributeError, subprocess.CalledProcessError):
            return size(rows=0, columns=0)


def get_advisory(vuln):
    return vuln.advisory if vuln.advisory else "No advisory found for this vulnerability."


class SheetReport(object):
    REPORT_BANNER = r"""
+==============================================================================+
|                                                                              |
|                               /$$$$$$            /$$                         |
|                              /$$__  $$          | $$                         |
|           /$$$$$$$  /$$$$$$ | $$  \__//$$$$$$  /$$$$$$   /$$   /$$           |
|          /$$_____/ |____  $$| $$$$   /$$__  $$|_  $$_/  | $$  | $$           |
|         |  $$$$$$   /$$$$$$$| $$_/  | $$$$$$$$  | $$    | $$  | $$           |
|          \____  $$ /$$__  $$| $$    | $$_____/  | $$ /$$| $$  | $$           |
|          /$$$$$$$/|  $$$$$$$| $$    |  $$$$$$$  |  $$$$/|  $$$$$$$           |
|         |_______/  \_______/|__/     \_______/   \___/   \____  $$           |
|                                                          /$$  | $$           |
|                                                         |  $$$$$$/           |
|  by pyup.io                                              \______/            |
|                                                                              |
+==============================================================================+
    """.strip()

    TABLE_HEADING = r"""
+============================+===========+==========================+==========+
| package                    | installed | affected                 | ID       |
+============================+===========+==========================+==========+
    """.strip()

    TABLE_HEADING_LICENSES = r"""
+=============================================+===========+====================+
| package                                     |  version  | license            |
+=============================================+===========+====================+
    """.strip()

    REPORT_HEADING = r"""
| REPORT                                                                       |
    """.strip()

    REPORT_SECTION = r"""
+==============================================================================+
    """.strip()

    REPORT_FOOTER = r"""
+==============================================================================+
    """.strip()

    @staticmethod
    def render(vulns, full, checked_packages, used_db):
        db_format_str = '{: <' + str(51 - len(str(checked_packages))) + '}'
        status = "| checked {packages} packages, using {db} |".format(
            packages=checked_packages,
            db=db_format_str.format(used_db),
            section=SheetReport.REPORT_SECTION
        )
        if vulns:
            table = []
            for n, vuln in enumerate(vulns):
                table.append("| {:26} | {:9} | {:24} | {:8} |".format(
                    vuln.name[:26],
                    vuln.version[:9],
                    vuln.spec[:24],
                    vuln.vuln_id
                ))
                if full:
                    table.append(SheetReport.REPORT_SECTION)

                    if vuln.cvssv2 is not None:
                        base_score = vuln.cvssv2.get("base_score", "None")
                        impact_score = vuln.cvssv2.get("impact_score", "None")

                        table.append("| {:76} |".format(
                            "CVSS v2 | BASE SCORE: {} | IMPACT SCORE: {}".format(
                                base_score,
                                impact_score,
                            )
                        ))
                        table.append(SheetReport.REPORT_SECTION)

                    if vuln.cvssv3 is not None:
                        base_score = vuln.cvssv3.get("base_score", "None")
                        impact_score = vuln.cvssv3.get("impact_score", "None")
                        base_severity = vuln.cvssv3.get("base_severity", "None")

                        table.append("| {:76} |".format(
                            "CVSS v3 | BASE SCORE: {} | IMPACT SCORE: {} | BASE SEVERITY: {}".format(
                                base_score,
                                impact_score,
                                base_severity,
                            )
                        ))
                        table.append(SheetReport.REPORT_SECTION)

                    advisory_lines = get_advisory(vuln).replace(
                        '\r', ''
                    ).splitlines()

                    for line in advisory_lines:
                        if line == '':
                            table.append("| {:76} |".format(" "))
                        for wrapped_line in textwrap.wrap(line, width=76):
                            try:
                                table.append("| {:76} |".format(
                                    wrapped_line.encode('utf-8')
                                ))
                            except TypeError:
                                table.append("| {:76} |".format(
                                    wrapped_line
                                ))
                    # append the REPORT_SECTION only if this isn't the last entry
                    if n + 1 < len(vulns):
                        table.append(SheetReport.REPORT_SECTION)
            return "\n".join(
                [SheetReport.REPORT_BANNER, SheetReport.REPORT_HEADING, status, SheetReport.TABLE_HEADING,
                 "\n".join(table), SheetReport.REPORT_FOOTER]
            )
        else:
            content = "| {:76} |".format("No known security vulnerabilities found.")
            return "\n".join(
                    [SheetReport.REPORT_BANNER, SheetReport.REPORT_HEADING, status, SheetReport.REPORT_SECTION,
                     content, SheetReport.REPORT_FOOTER]
                )

    @staticmethod
    def render_licenses(packages, packages_licenses):
        heading = SheetReport.REPORT_HEADING.replace(" ", "", 12).replace(
            "REPORT", " Packages licenses"
        )
        if not packages_licenses:
            content = "| {:76} |".format("No packages licenses found.")
            return "\n".join(
                    [SheetReport.REPORT_BANNER, heading, SheetReport.REPORT_SECTION,
                     content, SheetReport.REPORT_FOOTER]
                )

        table = []
        iteration = 1
        for pkg_license in packages_licenses:
            max_char = last_char = 43  # defines a limit for package name.
            current_line = 1
            package = pkg_license['package']
            license = pkg_license['license']
            version = pkg_license['version']
            license_line = int(int(len(package) / max_char) / 2) + 1  # Calc to get which line to add the license info.

            table.append("| {:43} | {:9} | {:18} |".format(
                package[:max_char],
                version[:9] if current_line == license_line else "",
                license[:18] if current_line == license_line else "",
            ))

            long_name = True if len(package[max_char:]) > 0 else False
            while long_name:  # If the package has a long name, break it into multiple lines.
                current_line += 1
                table.append("| {:43} | {:9} | {:18} |".format(
                    package[last_char:last_char+max_char],
                    version[:9] if current_line == license_line else "",
                    license[:18] if current_line == license_line else "",
                ))
                last_char = last_char+max_char
                long_name = True if len(package[last_char:]) > 0 else False

            if iteration != len(packages_licenses):  # Do not add dashes "----" for last package.
                table.append("|" + ("-" * 78) + "|")
            iteration += 1
        return "\n".join(
            [SheetReport.REPORT_BANNER, heading, SheetReport.TABLE_HEADING_LICENSES,
                "\n".join(table), SheetReport.REPORT_FOOTER]
        )

class BasicReport(object):
    """Basic report, intented to be used for terminals with < 80 columns"""

    @staticmethod
    def render(vulns, full, checked_packages, used_db):
        table = [
            "safety report",
            "checked {packages} packages, using {db}".format(
                packages=checked_packages,
                db=used_db
            ),
            "---"
        ]
        if vulns:

            for vuln in vulns:
                table.append("-> {}, installed {}, affected {}, id {}".format(
                    vuln.name,
                    vuln.version[:13],
                    vuln.spec[:27],
                    vuln.vuln_id
                ))
                if full:
                    if vuln.cvssv2 is not None:
                        base_score = vuln.cvssv2.get("base_score", "None")
                        impact_score = vuln.cvssv2.get("impact_score", "None")

                        table.append("CVSS v2 -- BASE SCORE: {}, IMPACT SCORE: {}".format(
                            base_score,
                            impact_score,
                        ))

                    if vuln.cvssv3 is not None:
                        base_score = vuln.cvssv3.get("base_score", "None")
                        impact_score = vuln.cvssv3.get("impact_score", "None")
                        base_severity = vuln.cvssv3.get("base_severity", "None")

                        table.append("CVSS v3 -- BASE SCORE: {}, IMPACT SCORE: {}, BASE SEVERITY: {}".format(
                            base_score,
                            impact_score,
                            base_severity,
                        ))

                    table.append(get_advisory(vuln))
                    table.append("--")
        else:
            table.append("No known security vulnerabilities found.")
        return "\n".join(
            table
        )

    @staticmethod
    def render_licenses(packages, packages_licenses):
        table = [
            "safety",
            "packages licenses",
            "---"
        ]
        if not packages_licenses:
            table.append("No packages licenses found.")
            return "\n".join(table)
        
        for pkg_license in packages_licenses:
            text = pkg_license['package'] + \
                   ", version " + pkg_license['version'] + \
                   ", license " + pkg_license['license'] + "\n"
            table.append(text)
        
        return "\n".join(table)

class JsonReport(object):
    """Json report, for when the output is input for something else"""

    @staticmethod
    def render(vulns, full):
        return json.dumps(vulns, indent=4, sort_keys=True)
    
    @staticmethod
    def render_licenses(packages_licenses):
        return json.dumps(packages_licenses, indent=4, sort_keys=True)


class BareReport(object):
    """Bare report, for command line tools"""
    @staticmethod
    def render(vulns, full):
        return " ".join(set([v.name for v in vulns]))

    @staticmethod
    def render_licenses(packages_licenses):
        licenses = set([pkg_li.get('license') for pkg_li in packages_licenses])
        if "N/A" in licenses:
            licenses.remove("N/A")
        sorted_licenses = sorted(licenses)
        return " ".join(sorted_licenses)


def get_used_db(key, db):
    key = key if key else os.environ.get("SAFETY_API_KEY", False)
    if db:
        return "local DB"
    if key:
        return "pyup.io's DB"
    return "free DB (updated once a month)"


def report(vulns, full=False, json_report=False, bare_report=False, checked_packages=0, db=None, key=None):
    if bare_report:
        return BareReport.render(vulns, full=full)
    if json_report:
        return JsonReport.render(vulns, full=full)
    size = get_terminal_size()
    used_db = get_used_db(key=key, db=db)
    if size.columns >= 80:
        return SheetReport.render(vulns, full=full, checked_packages=checked_packages, used_db=used_db)
    return BasicReport.render(vulns, full=full, checked_packages=checked_packages, used_db=used_db)


def license_report(packages, licenses, json_report=False, bare_report=False):
    if json_report:
        return JsonReport.render_licenses(packages_licenses=licenses)
    elif bare_report:
        return BareReport.render_licenses(packages_licenses=licenses)

    size = get_terminal_size()
    if size.columns >= 80:
        return SheetReport.render_licenses(packages, licenses)
    return BasicReport.render_licenses(packages, licenses)
