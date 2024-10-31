import json as simplejson
import sys
from pathlib import Path

from pipenv import exceptions
from pipenv.utils import console, err
from pipenv.utils.processes import run_command
from pipenv.utils.requirements import BAD_PACKAGES


def do_graph(project, bare=False, json=False, json_tree=False, reverse=False):
    import json as jsonlib

    from pipenv.vendor import pipdeptree

    pipdeptree_path = Path(pipdeptree.__file__).parent
    try:
        python_path = project.python()
    except AttributeError:
        err.print(
            "[bold][red]Warning: Unable to display currently-installed dependency graph information here. "
            "Please run within a Pipenv project.[/red][/bold]",
        )
        sys.exit(1)
    except RuntimeError:
        pass

    # Only keep the json + json_tree incompatibility check
    if json and json_tree:
        err.print(
            "[bold][red]Warning: Using both --json and --json-tree together is not supported. "
            "Please select one of the two options.[/red][/bold]",
        )
        sys.exit(1)

    # Build command arguments list
    cmd_args = [python_path, str(pipdeptree_path), "-l"]

    # Add flags as needed - multiple flags now supported
    if json:
        cmd_args.append("--json")
    if json_tree:
        cmd_args.append("--json-tree")
    if reverse:
        cmd_args.append("--reverse")

    if not project.virtualenv_exists:
        err.echo(
            "[bold][red]Warning: No virtualenv has been created for this project yet! Consider "
            "running `pipenv install` first to automatically generate one for you or see "
            "`pipenv install --help` for further instructions.[/red][/bold]",
        )
        sys.exit(1)

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
            console.print(simplejson.dumps(data, indent=4))
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
                console.print(simplejson.dumps(data, indent=4))
                sys.exit(0)
        else:
            for line in c.stdout.strip().split("\n"):
                # Ignore bad packages as top level.
                if line.split("==")[0] in BAD_PACKAGES and not reverse:
                    continue

                # Bold top-level packages.
                if not line.startswith(" "):
                    console.print(f"[bold]{line}[/bold]")
                # Echo the rest.
                else:
                    console.print(line)
    else:
        console.print(c.stdout)

    if c.returncode != 0:
        err.print(
            f"[bold][red]ERROR: {c.stderr}[red][/bold]",
        )
    # Return its return code.
    sys.exit(c.returncode)
