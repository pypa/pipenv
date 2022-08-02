from collections import namedtuple
from datetime import datetime
from typing import NamedTuple


class DictConverter(object):

    def to_dict(self, **kwargs):
        pass


announcement_nmt = namedtuple('Announcement', ['type', 'message'])
remediation_nmt = namedtuple('Remediation', ['Package', 'closest_secure_version', 'secure_versions',
                                             'latest_package_version'])
cve_nmt = namedtuple('Cve', ['name', 'cvssv2', 'cvssv3'])
severity_nmt = namedtuple('Severity', ['source', 'cvssv2', 'cvssv3'])
vulnerability_nmt = namedtuple('Vulnerability',
                               ['vulnerability_id', 'package_name', 'pkg', 'ignored', 'ignored_reason', 'ignored_expires',
                                'vulnerable_spec', 'all_vulnerable_specs', 'analyzed_version', 'advisory',
                                'is_transitive', 'published_date', 'fixed_versions',
                                'closest_versions_without_known_vulnerabilities', 'resources', 'CVE', 'severity',
                                'affected_versions', 'more_info_url'])
package_nmt = namedtuple('Package', ['name', 'version', 'found', 'insecure_versions', 'secure_versions',
                                     'latest_version_without_known_vulnerabilities', 'latest_version', 'more_info_url'])
package_nmt.__new__.__defaults__ = (None,) * len(package_nmt._fields)  # Ugly hack for now
RequirementFile = namedtuple('RequirementFile', ['path'])


class Package(package_nmt, DictConverter):

    def to_dict(self, **kwargs):
        if kwargs.get('short_version', False):
            return {
                'name': self.name,
                'version': self.version,
            }

        return {'name': self.name,
                'version': self.version,
                'found': self.found,
                'insecure_versions': self.insecure_versions,
                'secure_versions': self.secure_versions,
                'latest_version_without_known_vulnerabilities': self.latest_version_without_known_vulnerabilities,
                'latest_version': self.latest_version,
                'more_info_url': self.more_info_url
                }


class Announcement(announcement_nmt):
    pass


class Remediation(remediation_nmt, DictConverter):

    def to_dict(self):
        return {'package': self.Package.name,
                'closest_secure_version': self.closest_secure_version,
                'secure_versions': self.secure_versions,
                'latest_package_version': self.latest_package_version
                }


class CVE(cve_nmt, DictConverter):

    def to_dict(self):
        return {'name': self.name, 'cvssv2': self.cvssv2, 'cvssv3': self.cvssv3}


class Severity(severity_nmt, DictConverter):
    def to_dict(self):
        result = {'severity': {'source': self.source}}

        result['severity']['cvssv2'] = self.cvssv2
        result['severity']['cvssv3'] = self.cvssv3

        return result


class Vulnerability(vulnerability_nmt):

    def to_dict(self):
        empty_list_if_none = ['fixed_versions', 'closest_versions_without_known_vulnerabilities', 'resources']
        result = {
        }

        ignore = ['pkg']

        for field, value in zip(self._fields, self):
            if field in ignore:
                continue

            if value is None and field in empty_list_if_none:
                value = []

            if isinstance(value, CVE):
                val = None
                if value.name.startswith("CVE"):
                    val = value.name
                result[field] = val
            elif isinstance(value, DictConverter):
                result.update(value.to_dict())
            elif isinstance(value, datetime):
                result[field] = str(value)
            else:
                result[field] = value

        return result

    def get_advisory(self):
        return self.advisory.replace('\r', '') if self.advisory else "No advisory found for this vulnerability."
