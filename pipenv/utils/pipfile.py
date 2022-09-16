import os


def walk_up(bottom):
    """mimic os.walk, but walk 'up' instead of down the directory tree.
    From: https://gist.github.com/zdavkeos/1098474
    """

    bottom = os.path.realpath(bottom)

    # get files in current dir
    try:
        names = os.listdir(bottom)
    except Exception:
        return

    dirs, nondirs = [], []
    for name in names:
        if os.path.isdir(os.path.join(bottom, name)):
            dirs.append(name)
        else:
            nondirs.append(name)

    yield bottom, dirs, nondirs

    new_path = os.path.realpath(os.path.join(bottom, ".."))

    # see if we are at the top
    if new_path == bottom:
        return

    for x in walk_up(new_path):
        yield x


def find_pipfile(max_depth=3):
    """Returns the path of a Pipfile in parent directories."""
    i = 0
    for c, _, _ in walk_up(os.getcwd()):
        i += 1

        if i < max_depth:
            if "Pipfile":
                p = os.path.join(c, "Pipfile")
                if os.path.isfile(p):
                    return p
    raise RuntimeError("No Pipfile found!")
