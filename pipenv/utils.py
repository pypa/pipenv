import delegator
import click
import requirements
import tempfile


def format_toml(data):
    """Pretty-formats a given toml string."""
    data = data.split('\n')
    for i, line in enumerate(data):
        if i > 0:
            if line.startswith('['):
                data[i] = '\n{}'.format(line)

    return '\n'.join(data)



def multi_split(s, split):
    """Splits on multiple given separators."""
    for r in split:
        s = s.replace(r, '|')

    return [i for i in s.split('|') if len(i) > 0]


def convert_deps_from_pip(dep):
    """"Converts a pip-formatted dependency to a Pipfile-formatted one."""
    dependency = {}

    req = [r for r in requirements.parse(dep)][0]

    # Comparison operators: e.g. Django>1.10
    if req.specs:
        r = multi_split(dep, '=<>')
        dependency[req.name] = dep[len(r[0]):]

    # Extras: e.g. requests[socks]
    elif req.extras:
        r = multi_split(dep, '[]')
        dependency[req.name] = {'extras': req.extras}

    # VCS Installs.
    elif req.vcs:
        # Crop off the git+, etc part.
        dependency[req.name] = {req.vcs: req.uri[len(req.vcs)+1:]}

        # Add --editable, if it's there.
        if req.editable:
            dependency[req.name].update({'editable': True})

        # Add the specifier, if it was provided.
        if req.revision:
            dependency[req.name].update({'ref': req.revision})

    # Bare dependencies: e.g. requests
    else:
        dependency[dep] = '*'

    return dependency


def convert_deps_to_pip(deps, r=True):
    """"Converts a Pipfile-formatteddependency to a pip-formatted one."""
    dependencies = []

    for dep in deps.keys():

        # Default (e.g. '>1.10').
        extra = deps[dep]
        version = ''

        # Get rid of '*'.
        if deps[dep] == '*' or str(extra) == '{}':
            extra = ''

        if 'hash' in deps[dep]:
            extra = ' --hash={0}'.format(deps[dep]['hash'])
            # extra = ''

        # Support for extras (e.g. requests[socks])
        if 'extras' in deps[dep]:
            extra = '[{0}]'.format(deps[dep]['extras'][0])

        if 'version' in deps[dep]:
            version = deps[dep]['version']

        # Support for git.
        # TODO: support SVN and others.
        if 'git' in deps[dep]:
            extra = 'git+{0}'.format(deps[dep]['git'])

            # Support for @refs.
            if 'ref' in deps[dep]:
                extra += '@{0}'.format(deps[dep]['ref'])

            extra += '#egg={0}'.format(dep)

            # Support for editable.
            if 'editable' in deps[dep]:
                # Support for --egg.
                dep = '-e '
            else:
                dep = ''

        dependencies.append('{0}{1}{2}'.format(dep, version, extra))

    if not r:
        return dependencies

    # Write requirements.txt to tmp directory.
    f = tempfile.NamedTemporaryFile(suffix='-requirements.txt', delete=False)
    f.write('\n'.join(dependencies).encode('utf-8'))
    return f.name
