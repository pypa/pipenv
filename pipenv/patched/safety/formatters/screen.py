import pipenv.vendor.click as click

from pipenv.patched.safety.formatter import FormatterAPI
from pipenv.patched.safety.output_utils import build_announcements_section_content, format_long_text, \
    add_empty_line, format_vulnerability, get_final_brief, \
    build_report_brief_section, format_license, get_final_brief_license, build_remediation_section, \
    build_primary_announcement
from pipenv.patched.safety.util import get_primary_announcement, get_basic_announcements, get_terminal_size


class ScreenReport(FormatterAPI):
    DIVIDER_SECTIONS = '+' + '=' * (get_terminal_size().columns - 2) + '+'

    REPORT_BANNER = DIVIDER_SECTIONS + '\n' + r"""
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

""" + DIVIDER_SECTIONS

    ANNOUNCEMENTS_HEADING = format_long_text(click.style('ANNOUNCEMENTS', bold=True))

    def __build_announcements_section(self, announcements):
        announcements_section = []

        basic_announcements = get_basic_announcements(announcements)

        if basic_announcements:
            announcements_content = build_announcements_section_content(basic_announcements)
            announcements_section = [add_empty_line(), self.ANNOUNCEMENTS_HEADING, add_empty_line(),
                                     announcements_content, add_empty_line(), self.DIVIDER_SECTIONS]

        return announcements_section

    def render_vulnerabilities(self, announcements, vulnerabilities, remediations, full, packages):
        announcements_section = self.__build_announcements_section(announcements)
        primary_announcement = get_primary_announcement(announcements)
        remediation_section = build_remediation_section(remediations)
        end_content = []

        if primary_announcement:
            end_content = [add_empty_line(),
                           build_primary_announcement(primary_announcement, columns=get_terminal_size().columns),
                           self.DIVIDER_SECTIONS]

        table = []
        ignored = {}
        total_ignored = 0

        for n, vuln in enumerate(vulnerabilities):
            if vuln.ignored:
                total_ignored += 1
                ignored[vuln.package_name] = ignored.get(vuln.package_name, 0) + 1
            table.append(format_vulnerability(vuln, full))

        report_brief_section = build_report_brief_section(primary_announcement=primary_announcement, report_type=1,
                                                          vulnerabilities_found=max(0, len(vulnerabilities)-total_ignored),
                                                          vulnerabilities_ignored=total_ignored,
                                                          remediations_recommended=len(remediations))

        if vulnerabilities:

            final_brief = get_final_brief(len(vulnerabilities), len(remediations), ignored, total_ignored)

            return "\n".join(
                [ScreenReport.REPORT_BANNER] + announcements_section + [report_brief_section,
                                                                        add_empty_line(),
                                                                        self.DIVIDER_SECTIONS,
                                                                        format_long_text(
                                                                            click.style('VULNERABILITIES FOUND',
                                                                                        bold=True, fg='red')),
                                                                        self.DIVIDER_SECTIONS,
                                                                        add_empty_line(),
                                                                        "\n\n".join(table),
                                                                        final_brief,
                                                                        add_empty_line(),
                                                                        self.DIVIDER_SECTIONS] +
                remediation_section + end_content
            )
        else:
            content = format_long_text(click.style("No known security vulnerabilities found.", bold=True, fg='green'))
            return "\n".join(
                [ScreenReport.REPORT_BANNER] + announcements_section + [report_brief_section,
                                                                        self.DIVIDER_SECTIONS,
                                                                        add_empty_line(),
                                                                        content,
                                                                        add_empty_line(),
                                                                        self.DIVIDER_SECTIONS] +
                end_content
            )

    def render_licenses(self, announcements, licenses):
        unique_license_types = set([lic['license'] for lic in licenses])

        report_brief_section = build_report_brief_section(primary_announcement=get_primary_announcement(announcements),
                                                          report_type=2, licenses_found=len(unique_license_types))
        announcements_section = self.__build_announcements_section(announcements)

        if not licenses:
            content = format_long_text(click.style("No packages licenses found.", bold=True, fg='red'))
            return "\n".join(
                [ScreenReport.REPORT_BANNER] + announcements_section + [report_brief_section,
                                                                        self.DIVIDER_SECTIONS,
                                                                        add_empty_line(),
                                                                        content,
                                                                        add_empty_line(),
                                                                        self.DIVIDER_SECTIONS]
            )

        table = []
        for license in licenses:
            table.append(format_license(license))

        final_brief = get_final_brief_license(unique_license_types)

        return "\n".join(
            [ScreenReport.REPORT_BANNER] + announcements_section + [report_brief_section,
                                                                    add_empty_line(),
                                                                    self.DIVIDER_SECTIONS,
                                                                    format_long_text(
                                                                        click.style('LICENSES FOUND',
                                                                                    bold=True, fg='yellow')),
                                                                    self.DIVIDER_SECTIONS,
                                                                    add_empty_line(),
                                                                    "\n".join(table),
                                                                    final_brief,
                                                                    add_empty_line(),
                                                                    self.DIVIDER_SECTIONS]
        )

    def render_announcements(self, announcements):
        return self.__build_announcements_section(announcements)



