import json as simplejson
import os
import sys
from pathlib import Path

from pipenv import exceptions
from pipenv.utils.processes import run_command
from pipenv.utils.requirements import BAD_PACKAGES
from pipenv.vendor import click


def do_graph(project, bare=False, json=False, json_tree=False, reverse=False):
    import json as jsonlib

    from pipenv.vendor import pipdeptree

    pipdeptree_path = os.path.dirname(pipdeptree.__file__.rstrip("cdo"))
    try:
        python_path = project.python()
    except AttributeError:
        click.echo(
            "{}: {}".format(
                click.style("Warning", fg="red", bold=True),
                "Unable to display currently-installed dependency graph information here. "
                "Please run within a Pipenv project.",
            ),
            err=True,
        )
        sys.exit(1)
    except RuntimeError:
        pass
    else:
        if os.name != "nt":  # bugfix #4388
            python_path = Path(python_path).as_posix()
            pipdeptree_path = Path(pipdeptree_path).as_posix()

    if reverse and json:
        click.echo(
            "{}: {}".format(
                click.style("Warning", fg="red", bold=True),
                "Using both --reverse and --json together is not supported. "
                "Please select one of the two options.",
            ),
            err=True,
        )
        sys.exit(1)
    if reverse and json_tree:
        click.echo(
            "{}: {}".format(
                click.style("Warning", fg="red", bold=True),
                "Using both --reverse and --json-tree together is not supported. "
                "Please select one of the two options.",
            ),
            err=True,
        )
        sys.exit(1)
    if json and json_tree:
        click.echo(
            "{}: {}".format(
                click.style("Warning", fg="red", bold=True),
                "Using both --json and --json-tree together is not supported. "
                "Please select one of the two options.",
            ),
            err=True,
        )
        sys.exit(1)
    flag = ""
    if json:
        flag = "--json"
    if json_tree:
        flag = "--json-tree"
    if reverse:
        flag = "--reverse"
    if not project.virtualenv_exists:
        click.echo(
            "{}: No virtualenv has been created for this project yet! Consider "
            "running {} first to automatically generate one for you or see "
            "{} for further instructions.".format(
                click.style("Warning", fg="red", bold=True),
                click.style("`pipenv install`", fg="green"),
                click.style("`pipenv install --help`", fg="green"),
            ),
            err=True,
        )
        sys.exit(1)
    cmd_args = [python_path, pipdeptree_path, "-l"]
    if flag:
        cmd_args.append(flag)
    c = run_command(cmd_args, is_verbose=project.s.is_verbose())
    # Run dep-tree.
    if not bare:
        if json:
            data = []
            try:
                parsed = simplejson.loads(c.stdout.strip())
            except jsonlib.JSONDecodeError:
                raise exceptions.JSONParseError(c.stdout, c.stderr)
            else:
                data += [d for d in parsed if d["package"]["key"] not in BAD_PACKAGES]
            click.echo(simplejson.dumps(data, indent=4))
            sys.exit(0)
        elif json_tree:

            def traverse(obj):
                if isinstance(obj, list):
                    return [
                        traverse(package)
                        for package in obj
                        if package["key"] not in BAD_PACKAGES
                    ]
                else:
                    obj["dependencies"] = traverse(obj["dependencies"])
                    return obj

            try:
                parsed = simplejson.loads(c.stdout.strip())
            except jsonlib.JSONDecodeError:
                raise exceptions.JSONParseError(c.stdout, c.stderr)
            else:
                data = traverse(parsed)
                click.echo(simplejson.dumps(data, indent=4))
                sys.exit(0)
        else:
            for line in c.stdout.strip().split("\n"):
                # Ignore bad packages as top level.
                # TODO: This should probably be a "==" in + line.partition
                if line.split("==")[0] in BAD_PACKAGES and not reverse:
                    continue

                # Bold top-level packages.
                if not line.startswith(" "):
                    click.echo(click.style(line, bold=True))
                # Echo the rest.
                else:
                    click.echo(click.style(line, bold=False))
    else:
        click.echo(c.stdout)
    if c.returncode != 0:
        click.echo(
            "{} {}".format(
                click.style("ERROR: ", fg="red", bold=True),
                click.style(f"{c.stderr}", fg="white"),
            ),
            err=True,
        )
    # Return its return code.
    sys.exit(c.returncode)
