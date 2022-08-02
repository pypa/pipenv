from collections import namedtuple

from pipenv.patched.safety.formatter import FormatterAPI
from pipenv.patched.safety.util import get_basic_announcements


class BareReport(FormatterAPI):
    """Bare report, for command line tools"""

    def render_vulnerabilities(self, announcements, vulnerabilities, remediations, full, packages):
        parsed_announcements = []

        Announcement = namedtuple("Announcement", ["name"])

        for announcement in get_basic_announcements(announcements):
            normalized_message = "-".join(announcement.get('message', 'none').lower().split())
            parsed_announcements.append(Announcement(name=normalized_message))

        announcements_to_render = [announcement.name for announcement in parsed_announcements]
        affected_packages = list(set([v.package_name for v in vulnerabilities if not v.ignored]))

        return " ".join(announcements_to_render + affected_packages)

    def render_licenses(self, announcements, packages_licenses):
        parsed_announcements = []

        for announcement in get_basic_announcements(announcements):
            normalized_message = "-".join(announcement.get('message', 'none').lower().split())
            parsed_announcements.append({'license': normalized_message})

        announcements_to_render = [announcement.get('license') for announcement in parsed_announcements]

        licenses = list(set([pkg_li.get('license') for pkg_li in packages_licenses]))
        sorted_licenses = sorted(licenses)
        return " ".join(announcements_to_render + sorted_licenses)

    def render_announcements(self, announcements):
        print('render_announcements bare')
