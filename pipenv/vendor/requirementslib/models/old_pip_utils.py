"""These were old pip utils that were dropped starting in pip 22.1 but
`requirementslib` still deeply depends upon.

In the interest of getting the build working with the latest version of
pip again, this workaround to copy these dependent utils in was
provided. Ideally the code that depends on this behavior would be
modernized and refactored to not require it.
"""
import logging
import os
import shutil
import stat

logger = logging.getLogger(__name__)


from typing import Dict, Iterable, List


# This can be removed once this pr is merged
# https://github.com/python/cpython/pull/16575
def is_socket(path: str) -> bool:
    return stat.S_ISSOCK(os.lstat(path).st_mode)


def copy2_fixed(src: str, dest: str) -> None:
    """Wrap shutil.copy2() but map errors copying socket files to
    SpecialFileError as expected.

    See also https://bugs.python.org/issue37700.
    """
    try:
        shutil.copy2(src, dest)
    except OSError:
        for f in [src, dest]:
            try:
                is_socket_file = is_socket(f)
            except OSError:
                # An error has already occurred. Another error here is not
                # a problem and we can ignore it.
                pass
            else:
                if is_socket_file:
                    raise shutil.SpecialFileError("`{f}` is a socket".format(**locals()))

        raise


def _copy2_ignoring_special_files(src: str, dest: str) -> None:
    """Copying special files is not supported, but as a convenience to users we
    skip errors copying them.

    This supports tools that may create e.g. socket files in the project
    source directory.
    """
    try:
        copy2_fixed(src, dest)
    except shutil.SpecialFileError as e:
        # SpecialFileError may be raised due to either the source or
        # destination. If the destination was the cause then we would actually
        # care, but since the destination directory is deleted prior to
        # copy we ignore all of them assuming it is caused by the source.
        logger.warning(
            "Ignoring special file error '%s' encountered copying %s to %s.",
            str(e),
            src,
            dest,
        )


def _copy_source_tree(source: str, target: str) -> None:
    target_abspath = os.path.abspath(target)
    target_basename = os.path.basename(target_abspath)
    target_dirname = os.path.dirname(target_abspath)

    def ignore(d: str, names: List[str]) -> List[str]:
        skipped: List[str] = []
        if d == source:
            # Pulling in those directories can potentially be very slow,
            # exclude the following directories if they appear in the top
            # level dir (and only it).
            # See discussion at https://github.com/pypa/pip/pull/6770
            skipped += [".tox", ".nox"]
        if os.path.abspath(d) == target_dirname:
            # Prevent an infinite recursion if the target is in source.
            # This can happen when TMPDIR is set to ${PWD}/...
            # and we copy PWD to TMPDIR.
            skipped += [target_basename]
        return skipped

    shutil.copytree(
        source,
        target,
        ignore=ignore,
        symlinks=True,
        copy_function=_copy2_ignoring_special_files,
    )
