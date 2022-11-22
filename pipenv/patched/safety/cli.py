# -*- coding: utf-8 -*-
from __future__ import absolute_import

import json
import logging
import os
import sys
import tempfile

import pipenv.vendor.click as click

from pipenv.patched.safety import safety
from pipenv.patched.safety.alerts import alert
from pipenv.patched.safety.constants import EXIT_CODE_VULNERABILITIES_FOUND, EXIT_CODE_OK, EXIT_CODE_FAILURE
from pipenv.patched.safety.errors import SafetyException, SafetyError
from pipenv.patched.safety.formatter import SafetyFormatter
from pipenv.patched.safety.output_utils import should_add_nl
from pipenv.patched.safety.safety import get_packages, read_vulnerabilities, fetch_policy, post_results
from pipenv.patched.safety.util import get_proxy_dict, get_packages_licenses, output_exception, \
    MutuallyExclusiveOption, DependentOption, transform_ignore, SafetyPolicyFile, active_color_if_needed, \
    get_processed_options, get_safety_version, json_alias, bare_alias, SafetyContext, is_a_remote_mirror, \
    filter_announcements

LOG = logging.getLogger(__name__)


@click.group()
@click.option('--debug/--no-debug', default=False)
@click.option('--telemetry/--disable-telemetry', default=True, hidden=True)
@click.option('--disable-optional-telemetry-data', default=False, cls=MutuallyExclusiveOption,
              mutually_exclusive=["telemetry", "disable-telemetry"], is_flag=True, show_default=True)
@click.version_option(version=get_safety_version())
@click.pass_context
def cli(ctx, debug, telemetry, disable_optional_telemetry_data):
    """
    Safety checks Python dependencies for known security vulnerabilities and suggests the proper
    remediations for vulnerabilities detected. Safety can be run on developer machines, in CI/CD pipelines and
    on production systems.
    """
    SafetyContext().safety_source = 'cli'
    ctx.telemetry = telemetry and not disable_optional_telemetry_data
    level = logging.CRITICAL
    if debug:
        level = logging.DEBUG

    logging.basicConfig(format='%(asctime)s %(name)s => %(message)s', level=level)

    LOG.info(f'Telemetry enabled: {ctx.telemetry}')

    @ctx.call_on_close
    def clean_up_on_close():
        LOG.debug('Calling clean up on close function.')
        safety.close_session()


@cli.command()
@click.option("--key", default="", envvar="SAFETY_API_KEY",
              help="API Key for pyup.io's vulnerability database. Can be set as SAFETY_API_KEY "
                   "environment variable. Default: empty")
@click.option("--db", default="",
              help="Path to a local or remote vulnerability database. Default: empty")
@click.option("--full-report/--short-report", default=False, cls=MutuallyExclusiveOption,
              mutually_exclusive=["output", "json", "bare"],
              with_values={"output": ['json', 'bare'], "json": [True, False], "bare": [True, False]},
              help='Full reports include a security advisory (if available). Default: --short-report')
@click.option("--cache", is_flag=False, flag_value=60, default=0,
              help="Cache requests to the vulnerability database locally. Default: 0 seconds",
              hidden=True)
@click.option("--stdin", default=False, cls=MutuallyExclusiveOption, mutually_exclusive=["files"],
              help="Read input from stdin.", is_flag=True, show_default=True)
@click.option("files", "--file", "-r", multiple=True, type=click.File(), cls=MutuallyExclusiveOption,
              mutually_exclusive=["stdin"],
              help="Read input from one (or multiple) requirement files. Default: empty")
@click.option("--ignore", "-i", multiple=True, type=str, default=[], callback=transform_ignore,
              help="Ignore one (or multiple) vulnerabilities by ID. Default: empty")
@click.option('--json', default=False, cls=MutuallyExclusiveOption, mutually_exclusive=["output", "bare"],
              with_values={"output": ['screen', 'text', 'bare', 'json'], "bare": [True, False]}, callback=json_alias,
              hidden=True, is_flag=True, show_default=True)
@click.option('--bare', default=False, cls=MutuallyExclusiveOption, mutually_exclusive=["output", "json"],
              with_values={"output": ['screen', 'text', 'bare', 'json'], "json": [True, False]}, callback=bare_alias,
              hidden=True, is_flag=True, show_default=True)
@click.option('--output', "-o", type=click.Choice(['screen', 'text', 'json', 'bare'], case_sensitive=False),
              default='screen', callback=active_color_if_needed, envvar='SAFETY_OUTPUT')
@click.option("--proxy-protocol", "-pr", type=click.Choice(['http', 'https']), default='https', cls=DependentOption, required_options=['proxy_host'],
              help="Proxy protocol (https or http) --proxy-protocol")
@click.option("--proxy-host", "-ph", multiple=False, type=str, default=None,
              help="Proxy host IP or DNS --proxy-host")
@click.option("--proxy-port", "-pp", multiple=False, type=int, default=80, cls=DependentOption, required_options=['proxy_host'],
              help="Proxy port number --proxy-port")
@click.option("--exit-code/--continue-on-error", default=True,
              help="Output standard exit codes. Default: --exit-code")
@click.option("--policy-file", type=SafetyPolicyFile(), default='.safety-policy.yml',
              help="Define the policy file to be used")
@click.option("--audit-and-monitor/--disable-audit-and-monitor", default=True,
              help="Send results back to pyup.io for viewing on your dashboard. Requires an API key.")
@click.option("--project", default=None,
              help="Project to associate this scan with on pyup.io. Defaults to a canonicalized github style name if available, otherwise unknown")

@click.option("--save-json", default="", help="Path to where output file will be placed, if the path is a directory, "
                                              "Safety will use safety-report.json as filename. Default: empty")
@click.pass_context
def check(ctx, key, db, full_report, stdin, files, cache, ignore, output, json, bare, proxy_protocol, proxy_host, proxy_port,
          exit_code, policy_file, save_json, audit_and_monitor, project):
    """
    Find vulnerabilities in Python dependencies at the target provided.

    """
    LOG.info('Running check command')

    try:
        packages = get_packages(files, stdin)
        proxy_dictionary = get_proxy_dict(proxy_protocol, proxy_host, proxy_port)

        if key:
            server_policies = fetch_policy(key=key, proxy=proxy_dictionary)
            server_audit_and_monitor = server_policies["audit_and_monitor"]
            server_safety_policy = server_policies["safety_policy"]
        else:
            server_audit_and_monitor = False
            server_safety_policy = ""

        if server_safety_policy and policy_file:
            click.secho(
                "Warning: both a local policy file '{policy_filename}' and a server sent policy are present. "
                "Continuing with the local policy file.".format(policy_filename=policy_file['filename']),
                fg="yellow",
                file=sys.stderr
            )
        elif server_safety_policy:
            with tempfile.NamedTemporaryFile(prefix='server-safety-policy-') as tmp:
                tmp.write(server_safety_policy.encode('utf-8'))
                tmp.seek(0)

                policy_file = SafetyPolicyFile().convert(tmp.name, param=None, ctx=None)
                LOG.info('Using server side policy file')

        ignore_severity_rules = None
        ignore, ignore_severity_rules, exit_code = get_processed_options(policy_file, ignore,
                                                                         ignore_severity_rules, exit_code)

        is_env_scan = not stdin and not files
        params = {'stdin': stdin, 'files': files, 'policy_file': policy_file, 'continue_on_error': not exit_code,
                  'ignore_severity_rules': ignore_severity_rules, 'project': project, 'audit_and_monitor': server_audit_and_monitor and audit_and_monitor}
        LOG.info('Calling the check function')
        vulns, db_full = safety.check(packages=packages, key=key, db_mirror=db, cached=cache, ignore_vulns=ignore,
                                      ignore_severity_rules=ignore_severity_rules, proxy=proxy_dictionary,
                                      include_ignored=True, is_env_scan=is_env_scan, telemetry=ctx.parent.telemetry,
                                      params=params)
        LOG.debug('Vulnerabilities returned: %s', vulns)
        LOG.debug('full database returned is None: %s', db_full is None)

        LOG.info('Safety is going to calculate remediations')
        remediations = safety.calculate_remediations(vulns, db_full)

        announcements = []
        if not db or is_a_remote_mirror(db):
            LOG.info('Not local DB used, Getting announcements')
            announcements = safety.get_announcements(key=key, proxy=proxy_dictionary, telemetry=ctx.parent.telemetry)

        json_report = None
        if save_json or (server_audit_and_monitor and audit_and_monitor):
            default_name = 'safety-report.json'
            json_report = SafetyFormatter(output='json').render_vulnerabilities(announcements, vulns, remediations,
                                                                                full_report, packages)

            if server_audit_and_monitor and audit_and_monitor:
                policy_contents = ''
                if policy_file:
                    policy_contents = policy_file.get('raw', '')

                r = post_results(key=key, proxy=proxy_dictionary, safety_json=json_report, policy_file=policy_contents)
                SafetyContext().params['audit_and_monitor_url'] = r.get('url')

            if save_json:
                if os.path.isdir(save_json):
                    save_json = os.path.join(save_json, default_name)

                with open(save_json, 'w+') as output_json_file:
                    output_json_file.write(json_report)

        LOG.info('Safety is going to render the vulnerabilities report using %s output', output)
        if json_report and output == 'json':
            output_report = json_report
        else:
            output_report = SafetyFormatter(output=output).render_vulnerabilities(announcements, vulns, remediations,
                                                                                  full_report, packages)

        # Announcements are send to stderr if not terminal, it doesn't depend on "exit_code" value
        stderr_announcements = filter_announcements(announcements=announcements, by_type='error')
        if stderr_announcements and (not sys.stdout.isatty() and os.environ.get("SAFETY_OS_DESCRIPTION", None) != 'run'):
            LOG.info('sys.stdout is not a tty, error announcements are going to be send to stderr')
            click.secho(SafetyFormatter(output='text').render_announcements(stderr_announcements), fg="red",
                        file=sys.stderr)

        found_vulns = list(filter(lambda v: not v.ignored, vulns))
        LOG.info('Vulnerabilities found (Not ignored): %s', len(found_vulns))
        LOG.info('All vulnerabilities found (ignored and Not ignored): %s', len(vulns))

        click.secho(output_report, nl=should_add_nl(output, found_vulns), file=sys.stdout)

        if exit_code and found_vulns:
            LOG.info('Exiting with default code for vulnerabilities found')
            sys.exit(EXIT_CODE_VULNERABILITIES_FOUND)

        sys.exit(EXIT_CODE_OK)

    except SafetyError as e:
        LOG.exception('Expected SafetyError happened: %s', e)
        output_exception(e, exit_code_output=exit_code)
    except Exception as e:
        LOG.exception('Unexpected Exception happened: %s', e)
        exception = e if isinstance(e, SafetyException) else SafetyException(info=e)
        output_exception(exception, exit_code_output=exit_code)


@cli.command()
@click.option("--full-report/--short-report", default=False, cls=MutuallyExclusiveOption, mutually_exclusive=["output"], with_values={"output": ['json', 'bare']},
              help='Full reports include a security advisory (if available). Default: '
                   '--short-report')
@click.option('--output', "-o", type=click.Choice(['screen', 'text', 'json', 'bare'], case_sensitive=False),
              default='screen', callback=active_color_if_needed)
@click.option("file", "--file", "-f", type=click.File(), required=True,
              help="Read input from an insecure report file. Default: empty")
@click.pass_context
def review(ctx, full_report, output, file):
    """
    Show an output from a previous exported JSON report.
    """
    LOG.info('Running check command')
    report = {}

    try:
        report = read_vulnerabilities(file)
    except SafetyError as e:
        LOG.exception('Expected SafetyError happened: %s', e)
        output_exception(e, exit_code_output=True)
    except Exception as e:
        LOG.exception('Unexpected Exception happened: %s', e)
        exception = e if isinstance(e, SafetyException) else SafetyException(info=e)
        output_exception(exception, exit_code_output=True)

    params = {'file': file}
    vulns, remediations, packages = safety.review(report, params=params)

    announcements = safety.get_announcements(key=None, proxy=None, telemetry=ctx.parent.telemetry)
    output_report = SafetyFormatter(output=output).render_vulnerabilities(announcements, vulns, remediations,
                                                                          full_report, packages)

    found_vulns = list(filter(lambda v: not v.ignored, vulns))
    click.secho(output_report, nl=should_add_nl(output, found_vulns), file=sys.stdout)
    sys.exit(EXIT_CODE_OK)


@cli.command()
@click.option("--key", envvar="SAFETY_API_KEY",
              help="API Key for pyup.io's vulnerability database. Can be set as SAFETY_API_KEY "
                   "environment variable. Default: empty")
@click.option("--db", default="",
              help="Path to a local license database. Default: empty")
@click.option('--output', "-o", type=click.Choice(['screen', 'text', 'json', 'bare'], case_sensitive=False),
              default='screen')
@click.option("--cache", default=0,
              help='Whether license database file should be cached.'
                   'Default: 0 seconds')
@click.option("files", "--file", "-r", multiple=True, type=click.File(),
              help="Read input from one (or multiple) requirement files. Default: empty")
@click.option("proxyhost", "--proxy-host", "-ph", multiple=False, type=str, default=None,
              help="Proxy host IP or DNS --proxy-host")
@click.option("proxyport", "--proxy-port", "-pp", multiple=False, type=int, default=80,
              help="Proxy port number --proxy-port")
@click.option("proxyprotocol", "--proxy-protocol", "-pr", multiple=False, type=str, default='http',
              help="Proxy protocol (https or http) --proxy-protocol")
@click.pass_context
def license(ctx, key, db, output, cache, files, proxyprotocol, proxyhost, proxyport):
    """
    Find the open source licenses used by your Python dependencies.
    """
    LOG.info('Running license command')
    packages = get_packages(files, False)

    proxy_dictionary = get_proxy_dict(proxyprotocol, proxyhost, proxyport)
    licenses_db = {}

    try:
        licenses_db = safety.get_licenses(key=key, db_mirror=db, cached=cache, proxy=proxy_dictionary,
                                          telemetry=ctx.parent.telemetry)
    except SafetyError as e:
        LOG.exception('Expected SafetyError happened: %s', e)
        output_exception(e, exit_code_output=False)
    except Exception as e:
        LOG.exception('Unexpected Exception happened: %s', e)
        exception = e if isinstance(e, SafetyException) else SafetyException(info=e)
        output_exception(exception, exit_code_output=False)

    filtered_packages_licenses = get_packages_licenses(packages=packages, licenses_db=licenses_db)

    announcements = []
    if not db:
        announcements = safety.get_announcements(key=key, proxy=proxy_dictionary, telemetry=ctx.parent.telemetry)

    output_report = SafetyFormatter(output=output).render_licenses(announcements, filtered_packages_licenses)

    click.secho(output_report, nl=True)


@cli.command()
@click.option("--path", default=".", help="Path where the generated file will be saved. Default: current directory")
@click.argument('name')
@click.pass_context
def generate(ctx, name, path):
    """Create a boilerplate supported file type.

    NAME is the name of the file type to generate. Valid values are: policy_file
    """
    if name != 'policy_file':
        click.secho(f'This Safety version only supports "policy_file" generation. "{name}" is not supported.', fg='red',
                    file=sys.stderr)
        sys.exit(EXIT_CODE_FAILURE)

    LOG.info('Running generate %s', name)

    if not os.path.exists(path):
        click.secho(f'The path "{path}" does not exist.', fg='red',
                    file=sys.stderr)
        sys.exit(EXIT_CODE_FAILURE)

    policy = os.path.join(path, '.safety-policy.yml')
    ROOT = os.path.dirname(os.path.abspath(__file__))

    try:
        with open(policy, "w") as f:
            f.write(open(os.path.join(ROOT, 'safety-policy-template.yml')).read())
            LOG.debug('Safety created the policy file.')
            msg = f'A default Safety policy file has been generated! Review the file contents in the path {path} in the ' \
                  'file: .safety-policy.yml'
            click.secho(msg, fg='green')
    except Exception as exc:
        if isinstance(exc, OSError):
            LOG.debug('Unable to generate %s because: %s', name, exc.errno)

        click.secho(f'Unable to generate {name}, because: {str(exc)} error.', fg='red',
                    file=sys.stderr)
        sys.exit(EXIT_CODE_FAILURE)


@cli.command()
@click.option("--path", default=".safety-policy.yml", help="Path where the generated file will be saved. Default: current directory")
@click.argument('name')
@click.pass_context
def validate(ctx, name, path):
    """Verify the validity of a supported file type.

    NAME is the name of the file type to validate. Valid values are: policy_file
    """
    if name != 'policy_file':
        click.secho(f'This Safety version only supports "policy_file" validation. "{name}" is not supported.', fg='red',
                    file=sys.stderr)
        sys.exit(EXIT_CODE_FAILURE)

    LOG.info('Running validate %s', name)

    if not os.path.exists(path):
        click.secho(f'The path "{path}" does not exist.', fg='red', file=sys.stderr)
        sys.exit(EXIT_CODE_FAILURE)

    try:
        values = SafetyPolicyFile().convert(path, None, None)
    except Exception as e:
        click.secho(str(e).lstrip(), fg='red', file=sys.stderr)
        sys.exit(EXIT_CODE_FAILURE)

    del values['raw']

    click.secho(f'The Safety policy file was successfully parsed with the following values:', fg='green')
    click.secho(json.dumps(values, indent=4, default=str))

cli.add_command(alert)


if __name__ == "__main__":
    cli()
