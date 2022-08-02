import pipenv.vendor.click as click

from pipenv.patched.safety.formatter import FormatterAPI
from pipenv.patched.safety.output_utils import build_announcements_section_content, format_vulnerability, \
    build_report_brief_section, get_final_brief_license, add_empty_line, get_final_brief, build_remediation_section, \
    build_primary_announcement
from pipenv.patched.safety.util import get_primary_announcement, get_basic_announcements


class TextReport(FormatterAPI):
    """Basic report, intented to be used for terminals with < 80 columns"""

    SMALL_DIVIDER_SECTIONS = '+' + '=' * 78 + '+'

    TEXT_REPORT_BANNER = SMALL_DIVIDER_SECTIONS + '\n' + r"""
                                   /$$$$$$            /$$
                                  /$$__  $$          | $$
               /$$$$$$$  /$$$$$$ | $$  \__//$$$$$$  /$$$$$$   /$$   /$$
              /$$_____/ |____  $$| $$$$   /$$__  $$|_  $$_/  | $$  | $$
             |  $$$$$$   /$$$$$$$| $$_/  | $$$$$$$$  | $$    | $$  | $$
              \____  $$ /$$__  $$| $$    | $$_____/  | $$ /$$| $$  | $$
              /$$$$$$$/|  $$$$$$$| $$    |  $$$$$$$  |  $$$$/|  $$$$$$$
             |_______/  \_______/|__/     \_______/   \___/   \____  $$
                                                              /$$  | $$
                                                             |  $$$$$$/
      by pyup.io                                              \______/

""" + SMALL_DIVIDER_SECTIONS

    def __build_announcements_section(self, announcements):
        announcements_table = []

        basic_announcements = get_basic_announcements(announcements)

        if basic_announcements:
            announcements_content = click.unstyle(build_announcements_section_content(basic_announcements,
                                                                                      columns=80,
                                                                                      start_line_decorator=' ' * 2,
                                                                                      end_line_decorator=''))
            announcements_table = [add_empty_line(), 'ANNOUNCEMENTS', add_empty_line(),
                                   announcements_content, add_empty_line(), self.SMALL_DIVIDER_SECTIONS]

        return announcements_table

    def render_vulnerabilities(self, announcements, vulnerabilities, remediations, full, packages):
        primary_announcement = get_primary_announcement(announcements)
        remediation_section = [click.unstyle(rem) for rem in build_remediation_section(remediations, columns=80)]
        end_content = []

        if primary_announcement:
            end_content = [add_empty_line(),
                           build_primary_announcement(primary_announcement, columns=80, only_text=True),
                           self.SMALL_DIVIDER_SECTIONS]

        announcement_section = self.__build_announcements_section(announcements)

        ignored = {}
        total_ignored = 0

        for n, vuln in enumerate(vulnerabilities):
            if vuln.ignored:
                total_ignored += 1
                ignored[vuln.package_name] = ignored.get(vuln.package_name, 0) + 1

        report_brief_section = click.unstyle(
            build_report_brief_section(columns=80, primary_announcement=primary_announcement,
                                       vulnerabilities_found=max(0, len(vulnerabilities)-total_ignored),
                                       vulnerabilities_ignored=total_ignored,
                                       remediations_recommended=len(remediations)))

        table = [self.TEXT_REPORT_BANNER] + announcement_section + [
            report_brief_section,
            '',
            self.SMALL_DIVIDER_SECTIONS,
        ]

        if vulnerabilities:
            table += [" VULNERABILITIES FOUND", self.SMALL_DIVIDER_SECTIONS]

            for vuln in vulnerabilities:
                table.append('\n' + format_vulnerability(vuln, full, only_text=True, columns=80))

            final_brief = click.unstyle(get_final_brief(len(vulnerabilities), len(remediations), ignored, total_ignored,
                                                        kwargs={'columns': 80}))
            table += [final_brief, add_empty_line(), self.SMALL_DIVIDER_SECTIONS] + remediation_section + end_content

        else:
            table += [add_empty_line(), " No known security vulnerabilities found.", add_empty_line(),
                      self.SMALL_DIVIDER_SECTIONS] + end_content

        return "\n".join(
            table
        )

    def render_licenses(self, announcements, licenses):
        unique_license_types = set([lic['license'] for lic in licenses])

        report_brief_section = click.unstyle(
            build_report_brief_section(columns=80, primary_announcement=get_primary_announcement(announcements),
                                       licenses_found=len(unique_license_types)))

        packages_licenses = licenses
        announcements_table = self.__build_announcements_section(announcements)

        final_brief = click.unstyle(
            get_final_brief_license(unique_license_types, kwargs={'columns': 80}))

        table = [self.TEXT_REPORT_BANNER] + announcements_table + [
            report_brief_section,
            self.SMALL_DIVIDER_SECTIONS,
            " LICENSES",
            self.SMALL_DIVIDER_SECTIONS,
            add_empty_line(),
        ]

        if not packages_licenses:
            table.append("  No packages licenses found.")
            table += [final_brief, add_empty_line(), self.SMALL_DIVIDER_SECTIONS]

            return "\n".join(table)

        for pkg_license in packages_licenses:
            text = "  {0}, version {1}, license {2}\n".format(pkg_license['package'], pkg_license['version'],
                                                              pkg_license['license'])
            table.append(text)

        table += [final_brief, add_empty_line(), self.SMALL_DIVIDER_SECTIONS]

        return "\n".join(table)

    def render_announcements(self, announcements):
        rows = self.__build_announcements_section(announcements)
        rows.insert(0, self.SMALL_DIVIDER_SECTIONS)
        return '\n'.join(rows)
