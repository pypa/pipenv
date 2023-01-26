import json
import logging
import os
import textwrap
from datetime import datetime

import pipenv.vendor.click as click

from pipenv.patched.safety.constants import RED, YELLOW
from pipenv.patched.safety.util import get_safety_version, Package, get_terminal_size, \
    SafetyContext, build_telemetry_data, build_git_data, is_a_remote_mirror

LOG = logging.getLogger(__name__)


def build_announcements_section_content(announcements, columns=get_terminal_size().columns,
                                        start_line_decorator=' ', end_line_decorator=' '):
    section = ''

    for i, announcement in enumerate(announcements):

        color = ''
        if announcement.get('type') == 'error':
            color = RED
        elif announcement.get('type') == 'warning':
            color = YELLOW

        item = '{message}'.format(
            message=format_long_text('* ' + announcement.get('message'), color, columns,
                                                 start_line_decorator, end_line_decorator))
        section += '{item}'.format(item=item)

        if i + 1 < len(announcements):
            section += '\n'

    return section


def add_empty_line():
    return format_long_text('')


def style_lines(lines, columns, pre_processed_text='', start_line=' ' * 4, end_line=' ' * 4):
    styled_text = pre_processed_text

    for line in lines:
        styled_line = ''
        left_padding = ' ' * line.get('left_padding', 0)

        for i, word in enumerate(line.get('words', [])):
            if word.get('style', {}):
                text = ''

                if i == 0:
                    text = left_padding  # Include the line padding in the word to avoid Github issues
                    left_padding = ''  # Clean left padding to avoid be added two times

                text += word.get('value', '')

                styled_line += click.style(text=text, **word.get('style', {}))
            else:
                styled_line += word.get('value', '')

        styled_text += format_long_text(styled_line, columns=columns, start_line_decorator=start_line,
                                        end_line_decorator=end_line,
                                        left_padding=left_padding, **line.get('format', {})) + '\n'

    return styled_text


def format_vulnerability(vulnerability, full_mode, only_text=False, columns=get_terminal_size().columns):

    common_format = {'left_padding': 3, 'format': {'sub_indent': ' ' * 3, 'max_lines': None}}

    styled_vulnerability = [
        {'words': [{'style': {'bold': True}, 'value': 'Vulnerability ID: '}, {'value': vulnerability.vulnerability_id}]},
    ]

    vulnerability_spec = [
        {'words': [{'style': {'bold': True}, 'value': 'Affected spec: '}, {'value': vulnerability.vulnerable_spec}]}]

    cve = vulnerability.CVE

    cvssv2_line = None
    cve_lines = []

    if cve:
        if full_mode and cve.cvssv2:
            b = cve.cvssv2.get("base_score", "-")
            s = cve.cvssv2.get("impact_score", "-")
            v = cve.cvssv2.get("vector_string", "-")

            # Reset sub_indent as the left_margin is going to be applied in this case
            cvssv2_line = {'format': {'sub_indent': ''}, 'words': [
                {'value': f'CVSS v2, BASE SCORE {b}, IMPACT SCORE {s}, VECTOR STRING {v}'},
            ]}

        if cve.cvssv3 and "base_severity" in cve.cvssv3.keys():
            cvss_base_severity_style = {'bold': True}
            base_severity = cve.cvssv3.get("base_severity", "-")

            if base_severity.upper() in ['HIGH', 'CRITICAL']:
                cvss_base_severity_style['fg'] = 'red'

            b = cve.cvssv3.get("base_score", "-")

            if full_mode:
                s = cve.cvssv3.get("impact_score", "-")
                v = cve.cvssv3.get("vector_string", "-")

                cvssv3_text = f'CVSS v3, BASE SCORE {b}, IMPACT SCORE {s}, VECTOR STRING {v}'

            else:
                cvssv3_text = f'CVSS v3, BASE SCORE {b} '

            cve_lines = [
                {'words': [{'style': {'bold': True}, 'value': '{0} is '.format(cve.name)},
                           {'style': cvss_base_severity_style,
                            'value': f'{base_severity} SEVERITY => '},
                           {'value': cvssv3_text},
                           ]},
            ]

            if cvssv2_line:
                cve_lines.append(cvssv2_line)

        elif cve.name:
            cve_lines = [
                {'words': [{'style': {'bold': True}, 'value': cve.name}]}
            ]

    advisory_format = {'sub_indent': ' ' * 3, 'max_lines': None} if full_mode else {'sub_indent': ' ' * 3,
                                                                                    'max_lines': 2}

    basic_vuln_data_lines = [
        {'format': advisory_format, 'words': [
            {'style': {'bold': True}, 'value': 'ADVISORY: '},
            {'value': vulnerability.advisory.replace('\n', '')}]}
    ]

    if SafetyContext().key:
        fixed_version_line = {'words': [
            {'style': {'bold': True}, 'value': 'Fixed versions: '},
            {'value': ', '.join(vulnerability.fixed_versions) if vulnerability.fixed_versions else 'No known fix'}
        ]}

        basic_vuln_data_lines.append(fixed_version_line)

    more_info_line = [{'words': [{'style': {'bold': True}, 'value': 'For more information, please visit '},
                       {'value': click.style(vulnerability.more_info_url)}]}]

    vuln_title = f'-> Vulnerability found in {vulnerability.package_name} version {vulnerability.analyzed_version}\n'

    styled_text = click.style(vuln_title, fg='red')

    to_print = styled_vulnerability

    if not vulnerability.ignored:
        to_print += vulnerability_spec + basic_vuln_data_lines + cve_lines
    else:
        generic_reason = 'This vulnerability is being ignored'
        if vulnerability.ignored_expires:
            generic_reason += f" until {vulnerability.ignored_expires.strftime('%Y-%m-%d %H:%M:%S UTC')}. " \
                              f"See your configurations"

        specific_reason = None
        if vulnerability.ignored_reason:
            specific_reason = [
                {'words': [{'style': {'bold': True}, 'value': 'Reason: '}, {'value': vulnerability.ignored_reason}]}]

        expire_section = [{'words': [
            {'style': {'bold': True, 'fg': 'green'}, 'value': f'{generic_reason}.'}, ]}]

        if specific_reason:
            expire_section += specific_reason

        to_print += expire_section

    if cve:
        to_print += more_info_line

    to_print = [{**common_format, **line} for line in to_print]

    content = style_lines(to_print, columns, styled_text, start_line='', end_line='', )

    return click.unstyle(content) if only_text else content


def format_license(license, only_text=False, columns=get_terminal_size().columns):
    to_print = [
        {'words': [{'style': {'bold': True}, 'value': license['package']},
                   {'value': ' version {0} found using license '.format(license['version'])},
                   {'style': {'bold': True}, 'value': license['license']}
                   ]
         },
    ]

    content = style_lines(to_print, columns, '-> ', start_line='', end_line='')

    return click.unstyle(content) if only_text else content


def build_remediation_section(remediations, only_text=False, columns=get_terminal_size().columns, kwargs=None):
    columns -= 2
    left_padding = ' ' * 3

    if not kwargs:
        # Reset default params in the format_long_text func
        kwargs = {'left_padding': '', 'columns': columns, 'start_line_decorator': '', 'end_line_decorator': '',
                  'sub_indent': left_padding}

    END_SECTION = '+' + '=' * columns + '+'

    if not remediations:
        return []

    content = ''
    total_vulns = 0
    total_packages = len(remediations.keys())

    for pkg in remediations.keys():
        total_vulns += remediations[pkg]['vulns_found']
        upgrade_to = remediations[pkg]['closest_secure_version']['major']
        downgrade_to = remediations[pkg]['closest_secure_version']['minor']
        fix_version = None

        if upgrade_to:
            fix_version = str(upgrade_to)
        elif downgrade_to:
            fix_version = str(downgrade_to)

        new_line = '\n'

        other_options = [str(fix) for fix in remediations[pkg].get('secure_versions', []) if str(fix) != fix_version]
        raw_recommendation = f"We recommend upgrading to version {upgrade_to} of {pkg}."

        if other_options:
            raw_other_options = ', '.join(other_options)
            raw_pre_other_options = 'Other versions without known vulnerabilities are:'
            if len(other_options) == 1:
                raw_pre_other_options = 'Other version without known vulnerabilities is'
            raw_recommendation = f"{raw_recommendation} {raw_pre_other_options} " \
                                 f"{raw_other_options}"

        remediation_content = [
            f'{left_padding}The closest version with no known vulnerabilities is ' + click.style(upgrade_to, bold=True),
            new_line,
            click.style(f'{left_padding}{raw_recommendation}', bold=True, fg='green')
        ]

        if not fix_version:
            remediation_content = [new_line,
                click.style(f'{left_padding}There is no known fix for this vulnerability.', bold=True, fg='yellow')]

        text = 'vulnerabilities' if remediations[pkg]['vulns_found'] > 1 else 'vulnerability'

        raw_rem_title = f"-> {pkg} version {remediations[pkg]['version']} was found, " \
                        f"which has {remediations[pkg]['vulns_found']} {text}"

        remediation_title = click.style(raw_rem_title, fg=RED, bold=True)

        content += new_line + format_long_text(remediation_title, **kwargs) + new_line

        pre_content = remediation_content + [
                          f"{left_padding}For more information, please visit {remediations[pkg]['more_info_url']}",
                          f'{left_padding}Always check for breaking changes when upgrading packages.',
                          new_line]

        for i, element in enumerate(pre_content):
            content += format_long_text(element, **kwargs)

            if i + 1 < len(pre_content):
                content += '\n'

    title = format_long_text(click.style(f'{left_padding}REMEDIATIONS', fg='green', bold=True), **kwargs)

    body = [content]

    if not is_using_api_key():
        vuln_text = 'vulnerabilities were' if total_vulns != 1 else 'vulnerability was'
        pkg_text = 'packages' if total_packages > 1 else 'package'
        msg = "{0} {1} found in {2} {3}. " \
              "For detailed remediation & fix recommendations, upgrade to a commercial license."\
            .format(total_vulns, vuln_text, total_packages, pkg_text)
        content = '\n' + format_long_text(msg, left_padding=' ', columns=columns) + '\n'
        body = [content]

    body.append(END_SECTION)

    content = [title] + body

    if only_text:
        content = [click.unstyle(item) for item in content]

    return content


def get_final_brief(total_vulns_found, total_remediations, ignored, total_ignored, kwargs=None):
    if not kwargs:
        kwargs = {}

    total_vulns = max(0, total_vulns_found - total_ignored)

    vuln_text = 'vulnerabilities' if total_ignored > 1 else 'vulnerability'
    pkg_text = 'packages were' if len(ignored.keys()) > 1 else 'package was'

    policy_file_text = ' using a safety policy file' if is_using_a_safety_policy_file() else ''

    vuln_brief = f" {total_vulns} vulnerabilit{'y was' if total_vulns == 1 else 'ies were'} found."
    ignored_text = f' {total_ignored} {vuln_text} from {len(ignored.keys())} {pkg_text} ignored.' if ignored else ''
    remediation_text = f" {total_remediations} remediation{' was' if total_remediations == 1 else 's were'} " \
                       f"recommended." if is_using_api_key() else ''

    raw_brief = f"Scan was completed{policy_file_text}.{vuln_brief}{ignored_text}{remediation_text}"

    return format_long_text(raw_brief, start_line_decorator=' ', **kwargs)


def get_final_brief_license(licenses, kwargs=None):
    if not kwargs:
        kwargs = {}

    licenses_text = ' Scan was completed.'

    if licenses:
        licenses_text = 'The following software licenses were present in your system: {0}'.format(', '.join(licenses))

    return format_long_text("{0}".format(licenses_text), start_line_decorator=' ', **kwargs)


def format_long_text(text, color='', columns=get_terminal_size().columns, start_line_decorator=' ', end_line_decorator=' ', left_padding='', max_lines=None, styling=None, indent='', sub_indent=''):
    if not styling:
        styling = {}

    if color:
        styling.update({'fg': color})

    columns -= len(start_line_decorator) + len(end_line_decorator)
    formatted_lines = []
    lines = text.replace('\r', '').splitlines()

    for line in lines:
        base_format = "{:" + str(columns) + "}"
        if line == '':
            empty_line = base_format.format(" ")
            formatted_lines.append("{0}{1}{2}".format(start_line_decorator, empty_line, end_line_decorator))
        wrapped_lines = textwrap.wrap(line, width=columns, max_lines=max_lines, initial_indent=indent, subsequent_indent=sub_indent, placeholder='...')
        for wrapped_line in wrapped_lines:
            try:
                new_line = left_padding + wrapped_line.encode('utf-8')
            except TypeError:
                new_line = left_padding + wrapped_line

            if styling:
                new_line = click.style(new_line, **styling)

            formatted_lines.append(f"{start_line_decorator}{new_line}{end_line_decorator}")

    return "\n".join(formatted_lines)


def get_printable_list_of_scanned_items(scanning_target):
    context = SafetyContext()

    result = []
    scanned_items_data = []

    if scanning_target == 'environment':
        locations = set([pkg.found for pkg in context.packages if isinstance(pkg, Package)])

        for path in locations:
            result.append([{'styled': False, 'value': '-> ' + path}])
            scanned_items_data.append(path)

        if len(locations) <= 0:
            msg = 'No locations found in the environment'
            result.append([{'styled': False, 'value': msg}])
            scanned_items_data.append(msg)

    elif scanning_target == 'stdin':
        scanned_stdin = [pkg.name for pkg in context.packages if isinstance(pkg, Package)]
        value = 'No found packages in stdin'
        scanned_items_data = [value]

        if len(scanned_stdin) > 0:
            value = ', '.join(scanned_stdin)
            scanned_items_data = scanned_stdin

        result.append(
            [{'styled': False, 'value': value}])

    elif scanning_target == 'files':
        for file in context.params.get('files', []):
            result.append([{'styled': False, 'value': f'-> {file.name}'}])
            scanned_items_data.append(file.name)
    elif scanning_target == 'file':
        file = context.params.get('file', None)
        name = file.name if file else ''
        result.append([{'styled': False, 'value': f'-> {name}'}])
        scanned_items_data.append(name)

    return result, scanned_items_data


REPORT_HEADING = format_long_text(click.style('REPORT', bold=True))


def build_report_brief_section(columns=None, primary_announcement=None, report_type=1, **kwargs):
    if not columns:
        columns = get_terminal_size().columns

    styled_brief_lines = []

    if primary_announcement:
        styled_brief_lines.append(
            build_primary_announcement(columns=columns, primary_announcement=primary_announcement))

    for line in get_report_brief_info(report_type=report_type, **kwargs):
        ln = ''
        padding = ' ' * 2

        for i, words in enumerate(line):
            processed_words = words.get('value', '')
            if words.get('style', False):
                text = ''
                if i == 0:
                    text = padding
                    padding = ''
                text += processed_words

                processed_words = click.style(text, bold=True)

            ln += processed_words

        styled_brief_lines.append(format_long_text(ln, color='', columns=columns, start_line_decorator='',
                                                   left_padding=padding, end_line_decorator='', sub_indent=' ' * 2))

    return "\n".join([add_empty_line(), REPORT_HEADING, add_empty_line(), '\n'.join(styled_brief_lines)])


def build_report_for_review_vuln_report(as_dict=False):
    ctx = SafetyContext()
    report_from_file = ctx.review
    packages = ctx.packages

    if as_dict:
        return report_from_file

    policy_f_name = report_from_file.get('policy_file', None)
    safety_policy_used = []
    if policy_f_name:
        safety_policy_used = [
            {'style': False, 'value': '\nScanning using a security policy file'},
            {'style': True, 'value': ' {0}'.format(policy_f_name)},
        ]

    action_executed = [
        {'style': True, 'value': 'Scanning dependencies'},
        {'style': False, 'value': ' in your '},
        {'style': True, 'value': report_from_file.get('scan_target', '-') + ':'},
        ]

    scanned_items = []

    for name in report_from_file.get('scanned', []):
        scanned_items.append([{'styled': False, 'value': '-> ' + name}])

    nl = [{'style': False, 'value': ''}]
    using_sentence = build_using_sentence(report_from_file.get('api_key', None),
                                          report_from_file.get('local_database_path_used', None))
    scanned_count_sentence = build_scanned_count_sentence(packages)
    old_timestamp = report_from_file.get('timestamp', None)

    old_timestamp = [{'style': False, 'value': 'Report generated '}, {'style': True, 'value': old_timestamp}]
    now = str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    current_timestamp = [{'style': False, 'value': 'Timestamp '}, {'style': True, 'value': now}]

    brief_info = [[{'style': False, 'value': 'Safety '},
     {'style': True, 'value': 'v' + report_from_file.get('safety_version', '-')},
     {'style': False, 'value': ' is scanning for '},
     {'style': True, 'value': 'Vulnerabilities'},
     {'style': True, 'value': '...'}] + safety_policy_used, action_executed
     ] + [nl] + scanned_items + [nl] + [using_sentence] + [scanned_count_sentence] + [old_timestamp] + \
                 [current_timestamp]

    return brief_info


def build_using_sentence(key, db):
    key_sentence = []
    custom_integration = os.environ.get('SAFETY_CUSTOM_INTEGRATION',
                                        'false').lower() == 'true'

    if key:
        key_sentence = [{'style': True, 'value': 'an API KEY'},
                        {'style': False, 'value': ' and the '}]
        db_name = 'PyUp Commercial'
    elif db:
        if is_a_remote_mirror(db):
            if custom_integration:
                return []
            db_name = f"remote URL {db}"
        else:
            db_name = f"local file {db}"
    else:
        db_name = 'non-commercial'

    database_sentence = [{'style': True, 'value': db_name + ' database'}]

    return [{'style': False, 'value': 'Using '}] + key_sentence + database_sentence


def build_scanned_count_sentence(packages):
    scanned_count = 'No packages found'
    if len(packages) >= 1:
        scanned_count = 'Found and scanned {0} {1}'.format(len(packages),
                                                           'packages' if len(packages) > 1 else 'package')

    return [{'style': True, 'value': scanned_count}]


def add_warnings_if_needed(brief_info):
    ctx = SafetyContext()
    warnings = []

    if ctx.packages:
        if ctx.params.get('continue_on_error', False):
            warnings += [[{'style': True,
                           'value': '* Continue-on-error is enabled, so returning successful (0) exit code in all cases.'}]]

        if ctx.params.get('ignore_severity_rules', False) and not is_using_api_key():
            warnings += [[{'style': True,
                           'value': '* Could not filter by severity, please upgrade your account to include severity data.'}]]

    if warnings:
        brief_info += [[{'style': False, 'value': ''}]] + warnings


def get_report_brief_info(as_dict=False, report_type=1, **kwargs):
    LOG.info('get_report_brief_info: %s, %s, %s', as_dict, report_type, kwargs)

    context = SafetyContext()

    packages = [pkg for pkg in context.packages if isinstance(pkg, Package)]
    brief_data = {}
    command = context.command

    if command == 'review':
        review = build_report_for_review_vuln_report(as_dict)
        return review

    key = context.key
    db = context.db_mirror

    scanning_types = {'check': {'name': 'Vulnerabilities', 'action': 'Scanning dependencies', 'scanning_target': 'environment'}, # Files, Env or Stdin
                      'license': {'name': 'Licenses', 'action': 'Scanning licenses', 'scanning_target': 'environment'}, # Files or Env
                      'review': {'name': 'Report', 'action': 'Reading the report',
                                 'scanning_target': 'file'}} # From file

    targets = ['stdin', 'environment', 'files', 'file']
    for target in targets:
        if context.params.get(target, False):
            scanning_types[command]['scanning_target'] = target
            break

    scanning_target = scanning_types.get(context.command, {}).get('scanning_target', '')
    brief_data['scan_target'] = scanning_target
    scanned_items, data = get_printable_list_of_scanned_items(scanning_target)
    brief_data['scanned'] = data
    nl = [{'style': False, 'value': ''}]

    action_executed = [
        {'style': True, 'value': scanning_types.get(context.command, {}).get('action', '')},
        {'style': False, 'value': ' in your '},
        {'style': True, 'value': scanning_target + ':'},
        ]

    policy_file = context.params.get('policy_file', None)
    safety_policy_used = []

    brief_data['policy_file'] = policy_file.get('filename', '-') if policy_file else None
    brief_data['policy_file_source'] = 'server' if brief_data['policy_file'] and 'server-safety-policy' in brief_data['policy_file'] else 'local'

    if policy_file and policy_file.get('filename', False):
        safety_policy_used = [
            {'style': False, 'value': '\nScanning using a security policy file'},
            {'style': True, 'value': ' {0}'.format(policy_file.get('filename', '-'))},
        ]

    audit_and_monitor = []
    if context.params.get('audit_and_monitor'):
        logged_url = context.params.get('audit_and_monitor_url') if context.params.get('audit_and_monitor_url') else "https://pyup.io"
        audit_and_monitor = [
            {'style': False, 'value': '\nLogging scan results to'},
            {'style': True, 'value': ' {0}'.format(logged_url)},
        ]

    current_time = str(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    brief_data['api_key'] = bool(key)
    brief_data['local_database_path'] = db if db else None
    brief_data['safety_version'] = get_safety_version()
    brief_data['timestamp'] = current_time
    brief_data['packages_found'] = len(packages)
    # Vuln report
    additional_data = []
    if report_type == 1:
        brief_data['vulnerabilities_found'] = kwargs.get('vulnerabilities_found', 0)
        brief_data['vulnerabilities_ignored'] = kwargs.get('vulnerabilities_ignored', 0)
        brief_data['remediations_recommended'] = 0

        additional_data = [
            [{'style': True, 'value': str(brief_data['vulnerabilities_found'])},
             {'style': True, 'value': f' vulnerabilit{"y" if brief_data["vulnerabilities_found"] == 1 else "ies"} found'}],
            [{'style': True, 'value': str(brief_data['vulnerabilities_ignored'])},
             {'style': True, 'value': f' vulnerabilit{"y" if brief_data["vulnerabilities_ignored"] == 1 else "ies"} ignored'}],
        ]

        if is_using_api_key():
            brief_data['remediations_recommended'] = kwargs.get('remediations_recommended', 0)
            additional_data.extend(
                [[{'style': True, 'value': str(brief_data['remediations_recommended'])},
                 {'style': True, 'value':
                     f' remediation{"" if brief_data["remediations_recommended"] == 1 else "s"} recommended'}]])

    elif report_type == 2:
        brief_data['licenses_found'] = kwargs.get('licenses_found', 0)
        additional_data = [
            [{'style': True, 'value': str(brief_data['licenses_found'])},
             {'style': True, 'value': f' license {"type" if brief_data["licenses_found"] == 1 else "types"} found'}],
        ]

    brief_data['telemetry'] = build_telemetry_data()

    brief_data['git'] = build_git_data()
    brief_data['project'] = context.params.get('project', None)

    brief_data['json_version'] = 1

    using_sentence = build_using_sentence(key, db)
    using_sentence_section = [nl] if not using_sentence else [nl] + [build_using_sentence(key, db)]
    scanned_count_sentence = build_scanned_count_sentence(packages)

    timestamp = [{'style': False, 'value': 'Timestamp '}, {'style': True, 'value': current_time}]

    brief_info = [[{'style': False, 'value': 'Safety '},
     {'style': True, 'value': 'v' + get_safety_version()},
     {'style': False, 'value': ' is scanning for '},
     {'style': True, 'value': scanning_types.get(context.command, {}).get('name', '')},
     {'style': True, 'value': '...'}] + safety_policy_used + audit_and_monitor, action_executed
     ] + [nl] + scanned_items + using_sentence_section + [scanned_count_sentence] + [timestamp]

    brief_info.extend(additional_data)

    add_warnings_if_needed(brief_info)

    LOG.info('Brief info data: %s', brief_data)
    LOG.info('Brief info, styled output: %s', '\n\n LINE ---->\n ' + '\n\n LINE ---->\n '.join(map(str, brief_info)))

    return brief_data if as_dict else brief_info


def build_primary_announcement(primary_announcement, columns=None, only_text=False):
    lines = json.loads(primary_announcement.get('message'))

    for line in lines:
        if 'words' not in line:
            raise ValueError('Missing words keyword')
        if len(line['words']) <= 0:
            raise ValueError('No words in this line')
        for word in line['words']:
            if 'value' not in word or not word['value']:
                raise ValueError('Empty word or without value')

    message = style_lines(lines, columns, start_line='', end_line='')

    return click.unstyle(message) if only_text else message


def is_using_api_key():
    return bool(SafetyContext().key)


def is_using_a_safety_policy_file():
    return bool(SafetyContext().params.get('policy_file', None))


def should_add_nl(output, found_vulns):
    if output == 'bare' and not found_vulns:
        return False

    return True

