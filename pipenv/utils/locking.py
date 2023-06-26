import os
import stat
from contextlib import contextmanager
from tempfile import NamedTemporaryFile
from typing import Mapping

from .dependencies import clean_resolved_dep, pep423_name, translate_markers


def format_requirement_for_lockfile(req, markers_lookup, index_lookup, hashes=None):
    if req.specifiers:
        version = str(req.get_version)
    else:
        version = None
    index = index_lookup.get(req.normalized_name)
    markers = markers_lookup.get(req.normalized_name)
    req.index = index
    name, pf_entry = req.pipfile_entry
    name = pep423_name(req.name)
    entry = {}
    if isinstance(pf_entry, str):
        entry["version"] = pf_entry.lstrip("=")
    else:
        entry.update(pf_entry)
        if version is not None and not req.is_vcs:
            entry["version"] = version
        if req.line_instance.is_direct_url and not req.is_vcs:
            entry["file"] = req.req.uri
    if hashes:
        entry["hashes"] = sorted(set(hashes))
    entry["name"] = name
    if index:
        entry.update({"index": index})
    if markers:
        entry.update({"markers": markers})
    entry = translate_markers(entry)
    if req.vcs or req.editable:
        for key in ("index", "version", "file"):
            try:
                del entry[key]
            except KeyError:
                pass
    return name, entry


def get_locked_dep(dep, pipfile_section):
    entry = None
    cleaner_kwargs = {"is_top_level": False, "pipfile_entry": None}
    if isinstance(dep, Mapping) and dep.get("name"):
        dep_name = pep423_name(dep["name"])
        for pipfile_key, pipfile_entry in pipfile_section.items():
            if pep423_name(pipfile_key) == dep_name:
                entry = pipfile_entry

    if entry:
        cleaner_kwargs.update({"is_top_level": True, "pipfile_entry": entry})
    lockfile_entry = clean_resolved_dep(dep, **cleaner_kwargs)
    if entry and isinstance(entry, Mapping):
        version = entry.get("version", "") if entry else ""
    else:
        version = entry if entry else ""
    lockfile_name, lockfile_dict = lockfile_entry.copy().popitem()
    lockfile_version = lockfile_dict.get("version", "")
    # Keep pins from the lockfile
    if lockfile_version != version and version.startswith("==") and "*" not in version:
        lockfile_dict["version"] = version
    lockfile_entry[lockfile_name] = lockfile_dict
    return lockfile_entry


def prepare_lockfile(results, pipfile, lockfile):
    # from .vendor.requirementslib.utils import is_vcs
    for dep in results:
        if not dep:
            continue
        # Merge in any relevant information from the pipfile entry, including
        # markers, normalized names, URL info, etc that we may have dropped during lock
        # if not is_vcs(dep):
        lockfile_entry = get_locked_dep(dep, pipfile)
        name = next(iter(k for k in lockfile_entry.keys()))
        current_entry = lockfile.get(name)
        if current_entry:
            if not isinstance(current_entry, Mapping):
                lockfile[name] = lockfile_entry[name]
            else:
                lockfile[name].update(lockfile_entry[name])
                lockfile[name] = translate_markers(lockfile[name])
        else:
            lockfile[name] = lockfile_entry[name]
    return lockfile


@contextmanager
def atomic_open_for_write(target, binary=False, newline=None, encoding=None) -> None:
    """Atomically open `target` for writing.
    This is based on Lektor's `atomic_open()` utility, but simplified a lot
    to handle only writing, and skip many multi-process/thread edge cases
    handled by Werkzeug.
    :param str target: Target filename to write
    :param bool binary: Whether to open in binary mode, default False
    :param Optional[str] newline: The newline character to use when writing, determined
        from system if not supplied.
    :param Optional[str] encoding: The encoding to use when writing, defaults to system
        encoding.
    How this works:
    * Create a temp file (in the same directory of the actual target), and
      yield for surrounding code to write to it.
    * If some thing goes wrong, try to remove the temp file. The actual target
      is not touched whatsoever.
    * If everything goes well, close the temp file, and replace the actual
      target with this new file.
    .. code:: python
        >>> fn = "test_file.txt"
        >>> def read_test_file(filename=fn):
                with open(filename, 'r') as fh:
                    print(fh.read().strip())
        >>> with open(fn, "w") as fh:
                fh.write("this is some test text")
        >>> read_test_file()
        this is some test text
        >>> def raise_exception_while_writing(filename):
                with open(filename, "w") as fh:
                    fh.write("writing some new text")
                    raise RuntimeError("Uh oh, hope your file didn't get overwritten")
        >>> raise_exception_while_writing(fn)
        Traceback (most recent call last):
            ...
        RuntimeError: Uh oh, hope your file didn't get overwritten
        >>> read_test_file()
        writing some new text
        >>> def raise_exception_while_writing(filename):
                with atomic_open_for_write(filename) as fh:
                    fh.write("Overwriting all the text from before with even newer text")
                    raise RuntimeError("But did it get overwritten now?")
        >>> raise_exception_while_writing(fn)
            Traceback (most recent call last):
                ...
            RuntimeError: But did it get overwritten now?
        >>> read_test_file()
            writing some new text
    """

    mode = "w+b" if binary else "w"
    f = NamedTemporaryFile(
        dir=os.path.dirname(target),
        prefix=".__atomic-write",
        mode=mode,
        encoding=encoding,
        newline=newline,
        delete=False,
    )
    # set permissions to 0644
    try:
        os.chmod(f.name, stat.S_IWUSR | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass
    try:
        yield f
    except BaseException:
        f.close()
        try:
            os.remove(f.name)
        except OSError:
            pass
        raise
    else:
        f.close()
        try:
            os.remove(target)  # This is needed on Windows.
        except OSError:
            pass
        os.rename(f.name, target)  # No os.replace() on Python 2.
