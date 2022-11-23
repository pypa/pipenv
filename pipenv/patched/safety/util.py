import json
import logging
import os
import platform

import sys
from datetime import datetime
from difflib import SequenceMatcher
from threading import Lock
from typing import List

import pipenv.vendor.click as click
from pipenv.vendor.click import BadParameter
from pipenv.vendor.dparse import parse, filetypes
from pipenv.patched.pip._vendor.packaging.utils import canonicalize_name
from pipenv.patched.pip._vendor.packaging.version import parse as parse_version
from pipenv.vendor.ruamel.yaml import YAML
from pipenv.vendor.ruamel.yaml.error import MarkedYAMLError

from pipenv.patched.safety.constants import EXIT_CODE_FAILURE, EXIT_CODE_OK
from pipenv.patched.safety.models import Package, RequirementFile

LOG = logging.getLogger(__name__)


def is_a_remote_mirror(mirror):
    return mirror.startswith("http://") or mirror.startswith("https://")


def is_supported_by_parser(path):
    supported_types = (".txt", ".in", ".yml", ".ini", "Pipfile",
                       "Pipfile.lock", "setup.cfg", "poetry.lock")
    return path.endswith(supported_types)


def read_requirements(fh, resolve=True):
    """
    Reads requirements from a file like object and (optionally) from referenced files.
    :param fh: file like object to read from
    :param resolve: boolean. resolves referenced files.
    :return: generator
    """
    is_temp_file = not hasattr(fh, 'name')
    path = None
    found = 'temp_file'
    file_type = filetypes.requirements_txt

    if not is_temp_file and is_supported_by_parser(fh.name):
        LOG.debug('not temp and a compatible file')
        path = fh.name
        found = path
        file_type = None

    LOG.debug(f'Path: {path}')
    LOG.debug(f'File Type: {file_type}')
    LOG.debug('Trying to parse file using dparse...')
    content = fh.read()
    LOG.debug(f'Content: {content}')
    dependency_file = parse(content, path=path, resolve=resolve,
                            file_type=file_type)
    LOG.debug(f'Dependency file: {dependency_file.serialize()}')
    LOG.debug(f'Parsed, dependencies: {[dep.serialize() for dep in dependency_file.resolved_dependencies]}')
    for dep in dependency_file.resolved_dependencies:
        try:
            spec = next(iter(dep.specs))._spec
        except StopIteration:
            click.secho(
                f"Warning: unpinned requirement '{dep.name}' found in {path}, "
                "unable to check.",
                fg="yellow",
                file=sys.stderr
            )
            return

        version = spec[1]
        if spec[0] == '==':
            yield Package(name=dep.name, version=version,
                          found=found,
                          insecure_versions=[],
                          secure_versions=[], latest_version=None,
                          latest_version_without_known_vulnerabilities=None,
                          more_info_url=None)


def get_proxy_dict(proxy_protocol, proxy_host, proxy_port):
    if proxy_protocol and proxy_host and proxy_port:
        # Safety only uses https request, so only https dict will be passed to requests
        return {'https': f"{proxy_protocol}://{proxy_host}:{str(proxy_port)}"}
    return None


def get_license_name_by_id(license_id, db):
    licenses = db.get('licenses', [])
    for name, id in licenses.items():
        if id == license_id:
            return name
    return None


def get_flags_from_context():
    flags = {}
    context = click.get_current_context(silent=True)

    if context:
        for option in context.command.params:
            flags_per_opt = option.opts + option.secondary_opts
            for flag in flags_per_opt:
                flags[flag] = option.name

    return flags


def get_used_options():
    flags = get_flags_from_context()
    used_options = {}

    for arg in sys.argv:
        cleaned_arg = arg if '=' not in arg else arg.split('=')[0]
        if cleaned_arg in flags:
            option_used = flags.get(cleaned_arg)

            if option_used in used_options:
                used_options[option_used][cleaned_arg] = used_options[option_used].get(cleaned_arg, 0) + 1
            else:
                used_options[option_used] = {cleaned_arg: 1}

    return used_options


def get_safety_version():
    from pipenv.patched.safety import VERSION
    return VERSION


def get_primary_announcement(announcements):
    for announcement in announcements:
        if announcement.get('type', '').lower() == 'primary_announcement':
            try:
                from pipenv.patched.safety.output_utils import build_primary_announcement
                build_primary_announcement(announcement, columns=80)
            except Exception as e:
                LOG.debug(f'Failed to build primary announcement: {str(e)}')
                return None

            return announcement

    return None


def get_basic_announcements(announcements):
    return [announcement for announcement in announcements if
            announcement.get('type', '').lower() != 'primary_announcement']


def filter_announcements(announcements, by_type='error'):
    return [announcement for announcement in announcements if
            announcement.get('type', '').lower() == by_type]


def build_telemetry_data(telemetry=True):
    context = SafetyContext()

    body = {
        'os_type': os.environ.get("SAFETY_OS_TYPE", None) or platform.system(),
        'os_release': os.environ.get("SAFETY_OS_RELEASE", None) or platform.release(),
        'os_description': os.environ.get("SAFETY_OS_DESCRIPTION", None) or platform.platform(),
        'python_version': platform.python_version(),
        'safety_command': context.command,
        'safety_options': get_used_options()
    } if telemetry else {}

    body['safety_version'] = get_safety_version()
    body['safety_source'] = os.environ.get("SAFETY_SOURCE", None) or context.safety_source

    LOG.debug(f'Telemetry body built: {body}')

    return body


def build_git_data():
    import subprocess

    def git_command(commandline):
        return subprocess.run(commandline, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode('utf-8').strip()

    try:
        is_git = git_command(["git", "rev-parse", "--is-inside-work-tree"])
    except Exception:
        is_git = False

    if is_git == "true":
        result = {
            "branch": "",
            "tag": "",
            "commit": "",
            "dirty": "",
            "origin": ""
        }

        try:
            result['branch'] = git_command(["git", "symbolic-ref", "--short", "-q", "HEAD"])
            result['tag'] = git_command(["git", "describe", "--tags", "--exact-match"])

            commit = git_command(["git", "describe", '--match=""', '--always', '--abbrev=40', '--dirty'])
            result['dirty'] = commit.endswith('-dirty')
            result['commit'] = commit.split("-dirty")[0]

            result['origin'] = git_command(["git", "remote", "get-url", "origin"])
        except Exception:
            pass

        return result
    else:
        return {
            "error": "not-git-repo"
        }


def output_exception(exception, exit_code_output=True):
    click.secho(str(exception), fg="red", file=sys.stderr)

    if exit_code_output:
        exit_code = EXIT_CODE_FAILURE
        if hasattr(exception, 'get_exit_code'):
            exit_code = exception.get_exit_code()
    else:
        exit_code = EXIT_CODE_OK

    sys.exit(exit_code)


def get_processed_options(policy_file, ignore, ignore_severity_rules, exit_code):
    if policy_file:
        security = policy_file.get('security', {})
        source = click.get_current_context().get_parameter_source("exit_code")

        if not ignore:
            ignore = security.get('ignore-vulnerabilities', {})
        if source == click.core.ParameterSource.DEFAULT:
            exit_code = not security.get('continue-on-vulnerability-error', False)
        ignore_cvss_below = security.get('ignore-cvss-severity-below', 0.0)
        ignore_cvss_unknown = security.get('ignore-cvss-unknown-severity', False)
        ignore_severity_rules = {'ignore-cvss-severity-below': ignore_cvss_below,
                                 'ignore-cvss-unknown-severity': ignore_cvss_unknown}

    return ignore, ignore_severity_rules, exit_code


class MutuallyExclusiveOption(click.Option):
    def __init__(self, *args, **kwargs):
        self.mutually_exclusive = set(kwargs.pop('mutually_exclusive', []))
        self.with_values = kwargs.pop('with_values', {})
        help = kwargs.get('help', '')
        if self.mutually_exclusive:
            ex_str = ', '.join(["{0} with values {1}".format(item, self.with_values.get(item)) if item in self.with_values else item for item in self.mutually_exclusive])
            kwargs['help'] = help + (
                ' NOTE: This argument is mutually exclusive with '
                ' arguments: [' + ex_str + '].'
            )
        super(MutuallyExclusiveOption, self).__init__(*args, **kwargs)

    def handle_parse_result(self, ctx, opts, args):
        m_exclusive_used = self.mutually_exclusive.intersection(opts)
        option_used = m_exclusive_used and self.name in opts

        exclusive_value_used = False
        for used in m_exclusive_used:
            value_used = opts.get(used, None)
            if not isinstance(value_used, List):
                value_used = [value_used]
            if value_used and set(self.with_values.get(used, [])).intersection(value_used):
                exclusive_value_used = True

        if option_used and (not self.with_values or exclusive_value_used):
            options = ', '.join(self.opts)
            prohibited = ''.join(["\n * --{0} with {1}".format(item, self.with_values.get(
                        item)) if item in self.with_values else f"\n * {item}" for item in self.mutually_exclusive])
            raise click.UsageError(
                f"Illegal usage: `{options}` is mutually exclusive with: {prohibited}"
            )

        return super(MutuallyExclusiveOption, self).handle_parse_result(
            ctx,
            opts,
            args
        )


class DependentOption(click.Option):
    def __init__(self, *args, **kwargs):
        self.required_options = set(kwargs.pop('required_options', []))
        help = kwargs.get('help', '')
        if self.required_options:
            ex_str = ', '.join(self.required_options)
            kwargs['help'] = help + (
                ' NOTE: This argument requires the following flags '
                ' [' + ex_str + '].'
            )
        super(DependentOption, self).__init__(*args, **kwargs)

    def handle_parse_result(self, ctx, opts, args):
        missing_required_arguments = self.required_options.difference(opts) and self.name in opts

        if missing_required_arguments:
            raise click.UsageError(
                "Illegal usage: `{}` needs the "
                "arguments `{}`.".format(
                    self.name,
                    ', '.join(missing_required_arguments)
                )
            )

        return super(DependentOption, self).handle_parse_result(
            ctx,
            opts,
            args
        )


def transform_ignore(ctx, param, value):
    if isinstance(value, tuple):
        return dict(zip(value, [{'reason': '', 'expires': None} for _ in range(len(value))]))

    return {}


def active_color_if_needed(ctx, param, value):
    if value == 'screen':
        ctx.color = True

    color = os.environ.get("SAFETY_COLOR", None)

    if color is not None:
        color = color.lower()

        if color == '1' or color == 'true':
            ctx.color = True
        elif color == '0' or color == 'false':
            ctx.color = False

    return value


def json_alias(ctx, param, value):
    if value:
        os.environ['SAFETY_OUTPUT'] = 'json'
        return value


def bare_alias(ctx, param, value):
    if value:
        os.environ['SAFETY_OUTPUT'] = 'bare'
        return value


def get_terminal_size():
    from shutil import get_terminal_size as t_size
    # get_terminal_size can report 0, 0 if run from pseudo-terminal prior Python 3.11 versions

    columns = t_size().columns or 80
    lines = t_size().lines or 24

    return os.terminal_size((columns, lines))


def validate_expiration_date(expiration_date):
    d = None

    if expiration_date:
        try:
            d = datetime.strptime(expiration_date, '%Y-%m-%d')
        except ValueError as e:
            pass

        try:
            d = datetime.strptime(expiration_date, '%Y-%m-%d %H:%M:%S')
        except ValueError as e:
            pass

    return d


class SafetyPolicyFile(click.ParamType):
    """
       Custom Safety Policy file to hold validations
    """

    name = "filename"
    envvar_list_splitter = os.path.pathsep

    def __init__(
        self,
        mode: str = "r",
        encoding: str = None,
        errors: str = "strict",
        pure: bool = os.environ.get('SAFETY_PURE_YAML', 'false').lower() == 'true'
    ) -> None:
        self.mode = mode
        self.encoding = encoding
        self.errors = errors
        self.basic_msg = '\n' + click.style('Unable to load the Safety Policy file "{name}".', fg='red')
        self.pure = pure

    def to_info_dict(self):
        info_dict = super().to_info_dict()
        info_dict.update(mode=self.mode, encoding=self.encoding)
        return info_dict

    def fail_if_unrecognized_keys(self, used_keys, valid_keys, param=None, ctx=None, msg='{hint}', context_hint=''):
        for keyword in used_keys:
            if keyword not in valid_keys:
                match = None
                max_ratio = 0.0
                if isinstance(keyword, str):
                    for option in valid_keys:
                        ratio = SequenceMatcher(None, keyword, option).ratio()
                        if ratio > max_ratio:
                            match = option
                            max_ratio = ratio

                maybe_msg = f' Maybe you meant: {match}' if max_ratio > 0.7 else \
                            f' Valid keywords in this level are: {", ".join(valid_keys)}'

                self.fail(msg.format(hint=f'{context_hint}"{keyword}" is not a valid keyword.{maybe_msg}'), param, ctx)

    def fail_if_wrong_bool_value(self, keyword, value, msg='{hint}'):
        if value is not None and not isinstance(value, bool):
            self.fail(msg.format(hint=f"'{keyword}' value needs to be a boolean. "
                                      "You can use True, False, TRUE, FALSE, true or false"))

    def convert(self, value, param, ctx):
        try:

            if hasattr(value, "read") or hasattr(value, "write"):
                return value

            msg = self.basic_msg.format(name=value) + '\n' + click.style('HINT:', fg='yellow') + ' {hint}'

            f, _ = click.types.open_stream(
                value, self.mode, self.encoding, self.errors, atomic=False
            )
            filename = ''

            try:
                raw = f.read()
                yaml = YAML(typ='safe', pure=self.pure)
                safety_policy = yaml.load(raw)
                filename = f.name
                f.close()
            except Exception as e:
                show_parsed_hint = isinstance(e, MarkedYAMLError)
                hint = str(e)
                if show_parsed_hint:
                    hint = f'{str(e.problem).strip()} {str(e.context).strip()} {str(e.context_mark).strip()}'

                self.fail(msg.format(name=value, hint=hint), param, ctx)

            if not safety_policy or not isinstance(safety_policy, dict) or not safety_policy.get('security', None):
                self.fail(
                    msg.format(hint='you are missing the security root tag'), param, ctx)

            security_config = safety_policy.get('security', {})
            security_keys = ['ignore-cvss-severity-below', 'ignore-cvss-unknown-severity', 'ignore-vulnerabilities',
                             'continue-on-vulnerability-error']
            used_keys = security_config.keys()

            self.fail_if_unrecognized_keys(used_keys, security_keys, param=param, ctx=ctx, msg=msg,
                                           context_hint='"security" -> ')

            ignore_cvss_security_below = security_config.get('ignore-cvss-severity-below', None)

            if ignore_cvss_security_below:
                limit = 0.0

                try:
                    limit = float(ignore_cvss_security_below)
                except ValueError as e:
                    self.fail(msg.format(hint="'ignore-cvss-severity-below' value needs to be an integer or float."))

                if limit < 0 or limit > 10:
                    self.fail(msg.format(hint="'ignore-cvss-severity-below' needs to be a value between 0 and 10"))

            continue_on_vulnerability_error = security_config.get('continue-on-vulnerability-error', None)
            self.fail_if_wrong_bool_value('continue-on-vulnerability-error', continue_on_vulnerability_error, msg)

            ignore_cvss_unknown_severity = security_config.get('ignore-cvss-unknown-severity', None)
            self.fail_if_wrong_bool_value('ignore-cvss-unknown-severity', ignore_cvss_unknown_severity, msg)

            ignore_vulns = safety_policy.get('security', {}).get('ignore-vulnerabilities', {})

            if ignore_vulns:
                if not isinstance(ignore_vulns, dict):
                    self.fail(msg.format(hint="Vulnerability IDs under the 'ignore-vulnerabilities' key, need to "
                                              "follow the convention 'ID_NUMBER:', probably you are missing a colon."))

                normalized = {}

                for ignored_vuln_id, config in ignore_vulns.items():
                    ignored_vuln_config = config if config else {}

                    if not isinstance(ignored_vuln_config, dict):
                        self.fail(
                            msg.format(hint=f"Wrong configuration under the vulnerability with ID: {ignored_vuln_id}"))

                    context_msg = f'"security" -> "ignore-vulnerabilities" -> "{ignored_vuln_id}" -> '

                    self.fail_if_unrecognized_keys(ignored_vuln_config.keys(), ['reason', 'expires'], param=param,
                                                   ctx=ctx, msg=msg, context_hint=context_msg)

                    reason = ignored_vuln_config.get('reason', '')
                    reason = str(reason) if reason else None
                    expires = ignored_vuln_config.get('expires', '')
                    expires = str(expires) if expires else None

                    try:
                        if int(ignored_vuln_id) < 0:
                            raise ValueError('Negative Vulnerability ID')
                    except ValueError as e:
                        self.fail(msg.format(
                            hint=f"vulnerability id {ignored_vuln_id} under the 'ignore-vulnerabilities' root needs to "
                                 f"be a positive integer")
                        )

                    # Validate expires
                    d = validate_expiration_date(expires)

                    if expires and not d:
                        self.fail(msg.format(hint=f"{context_msg}expires: \"{expires}\" isn't a valid format "
                                                  f"for the expires keyword, "
                                                  "valid options are: YYYY-MM-DD or "
                                                  "YYYY-MM-DD HH:MM:SS")
                                  )

                    normalized[str(ignored_vuln_id)] = {'reason': reason, 'expires': d}

                safety_policy['security']['ignore-vulnerabilities'] = normalized
                safety_policy['filename'] = filename
                safety_policy['raw'] = raw
            else:
                safety_policy['security']['ignore-vulnerabilities'] = {}

            return safety_policy
        except BadParameter as expected_e:
            raise expected_e
        except Exception as e:
            # Don't fail in the default case
            if ctx and isinstance(e, OSError):
                source = ctx.get_parameter_source("policy_file")
                if e.errno == 2 and source == click.core.ParameterSource.DEFAULT and value == '.safety-policy.yml':
                    return None

            problem = click.style("Policy file YAML is not valid.")
            hint = click.style("HINT: ", fg='yellow') + str(e)
            self.fail(f"{problem}\n{hint}", param, ctx)

    def shell_complete(
        self, ctx: "Context", param: "Parameter", incomplete: str
    ):
        """Return a special completion marker that tells the completion
        system to use the shell to provide file path completions.

        :param ctx: Invocation context for this command.
        :param param: The parameter that is requesting completion.
        :param incomplete: Value being completed. May be empty.

        .. versionadded:: 8.0
        """
        from pipenv.vendor.click.shell_completion import CompletionItem

        return [CompletionItem(incomplete, type="file")]


class SingletonMeta(type):

    _instances = {}

    _lock = Lock()

    def __call__(cls, *args, **kwargs):
        with cls._lock:
            if cls not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[cls] = instance
        return cls._instances[cls]


class SafetyContext(metaclass=SingletonMeta):
    packages = None
    key = False
    db_mirror = False
    cached = None
    ignore_vulns = None
    ignore_severity_rules = None
    proxy = None
    include_ignored = False
    telemetry = None
    files = None
    stdin = None
    is_env_scan = None
    command = None
    review = None
    params = {}
    safety_source = 'code'


def sync_safety_context(f):
    def new_func(*args, **kwargs):
        ctx = SafetyContext()

        for attr in dir(ctx):
            if attr in kwargs:
                setattr(ctx, attr, kwargs.get(attr))

        return f(*args, **kwargs)

    return new_func


@sync_safety_context
def get_packages_licenses(packages=None, licenses_db=None):
    """Get the licenses for the specified packages based on their version.

    :param packages: packages list
    :param licenses_db: the licenses db in the raw form.
    :return: list of objects with the packages and their respectives licenses.
    """
    SafetyContext().command = 'license'

    if not packages:
        packages = []
    if not licenses_db:
        licenses_db = {}

    packages_licenses_db = licenses_db.get('packages', {})
    filtered_packages_licenses = []

    for pkg in packages:
        # Ignore recursive files not resolved
        if isinstance(pkg, RequirementFile):
            continue
        # normalize the package name
        pkg_name = canonicalize_name(pkg.name)
        # packages may have different licenses depending their version.
        pkg_licenses = packages_licenses_db.get(pkg_name, [])
        version_requested = parse_version(pkg.version)
        license_id = None
        license_name = None
        for pkg_version in pkg_licenses:
            license_start_version = parse_version(pkg_version['start_version'])
            # Stops and return the previous stored license when a new
            # license starts on a version above the requested one.
            if version_requested >= license_start_version:
                license_id = pkg_version['license_id']
            else:
                # We found the license for the version requested
                break

        if license_id:
            license_name = get_license_name_by_id(license_id, licenses_db)
        if not license_id or not license_name:
            license_name = "unknown"

        filtered_packages_licenses.append({
            "package": pkg_name,
            "version": pkg.version,
            "license": license_name
        })

    return filtered_packages_licenses
