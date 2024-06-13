import datetime
import os
import pathlib
import re
import subprocess
import sys

import invoke
import semver

from pipenv.utils.shell import temp_environ

from .vendoring import _get_git_root, drop_dir

VERSION_FILE = "pipenv/__version__.py"
ROOT = pathlib.Path(".").parent.parent.absolute()
PACKAGE_NAME = "pipenv"


def log(msg):
    print(f"[release] {msg}")


def get_version_file(ctx):
    return _get_git_root(ctx).joinpath(VERSION_FILE)


def find_version(ctx):
    version_file = get_version_file(ctx).read_text()
    version_match = re.search(r"^__version__ = ['\"]([^'\"]*)['\"]", version_file, re.M)
    if version_match:
        return version_match.group(1)
    raise RuntimeError("Unable to find version string.")


def get_history_file(ctx):
    return _get_git_root(ctx).joinpath("HISTORY.txt")


def get_dist_dir(ctx):
    return _get_git_root(ctx) / "dist"


def get_build_dir(ctx):
    return _get_git_root(ctx) / "build"


def _render_log():
    """Totally tap into Towncrier internals to get an in-memory result."""
    rendered = subprocess.check_output(["towncrier", "--draft"]).decode("utf-8")
    return rendered


release_help = {
    "dry_run": "No-op, simulate what would happen if run for real.",
    "pre": "Build a pre-release version, must be paired with a tag.",
}


@invoke.task(help=release_help)
def release(
    ctx,
    dry_run=False,
    pre=False,
):
    drop_dist_dirs(ctx)
    version = bump_version(
        ctx,
        dry_run=dry_run,
        pre=pre,
    )
    tag_content = _render_log()
    if dry_run:
        ctx.run("towncrier --draft > CHANGELOG.draft.md")
        log("would remove: news/*")
        log("would remove: CHANGELOG.draft.md")
        log("would update: pipenv/pipenv.1")
        log(f'Would commit with message: "Release v{version}"')
    else:
        if pre:
            log("generating towncrier draft...")
            ctx.run("towncrier --draft > CHANGELOG.draft.md")
            ctx.run(f"git add {get_version_file(ctx).as_posix()}")
        else:
            ctx.run("towncrier")
            ctx.run(f"git add CHANGELOG.md news/ {get_version_file(ctx).as_posix()}")
            log("removing changelog draft if present")
            draft_changelog = pathlib.Path("CHANGELOG.draft.md")
            if draft_changelog.exists():
                draft_changelog.unlink()
        log("generating man files...")
        generate_manual(ctx)
        ctx.run("git add pipenv/pipenv.1")
        ctx.run(f'git commit -m "Release v{version}"')

    tag_content = tag_content.replace('"', '\\"')
    if dry_run or pre:
        log(f"Generated tag content: {tag_content}")
        # draft_rstfile = "CHANGELOG.draft.rst"
        # markdown_path = pathlib.Path(draft_rstfile).with_suffix(".md")
        # generate_markdown(ctx, source_rstfile=draft_rstfile)
        # clean_mdchangelog(ctx, markdown_path.as_posix())
        # log(f"would generate markdown: {markdown_path.read_text()}")
        if not dry_run:
            ctx.run(f'git tag -a v{version} -m "Version v{version}\n\n{tag_content}"')
    else:
        # generate_markdown(ctx)
        # clean_mdchangelog(ctx)
        ctx.run(f'git tag -a v{version} -m "Version v{version}\n\n{tag_content}"')


def drop_dist_dirs(ctx):
    log("Dropping Dist dir...")
    drop_dir(get_dist_dir(ctx))
    log("Dropping build dir...")
    drop_dir(get_build_dir(ctx))


@invoke.task
def build_dists(ctx):
    drop_dist_dirs(ctx)
    py_version = ".".join(str(v) for v in sys.version_info[:2])
    env = {"PIPENV_PYTHON": py_version}
    with ctx.cd(ROOT.as_posix()), temp_environ():
        executable = ctx.run(
            "python -c 'import sys; print(sys.executable)'", hide=True
        ).stdout.strip()
        log(f"Building sdist using {executable} ....")
        os.environ["PIPENV_PYTHON"] = py_version
        ctx.run("pipenv install --dev", env=env)
        ctx.run("pipenv run pip install -e . --upgrade --upgrade-strategy=eager", env=env)
        log(f"Building wheel using python {py_version} ....")
        ctx.run("pipenv run python -m build", env=env)


@invoke.task(build_dists)
def upload_dists(ctx, repo="pypi"):
    dist_pattern = f'{PACKAGE_NAME.replace("-", "[-_]")}-*'
    artifacts = list(ROOT.joinpath("dist").glob(dist_pattern))
    filename_display = "\n".join(f"  {a}" for a in artifacts)
    print(f"[release] Will upload:\n{filename_display}")
    try:
        input("[release] Release ready. ENTER to upload, CTRL-C to abort: ")
    except KeyboardInterrupt:
        print("\nAborted!")
        return

    arg_display = " ".join(f'"{n}"' for n in artifacts)
    ctx.run(f'twine upload --repository="{repo}" {arg_display}')


@invoke.task
def generate_markdown(ctx, source_rstfile=None):
    log("Generating markdown from changelog...")
    if source_rstfile is None:
        source_rstfile = "CHANGELOG.md"
    source_file = pathlib.Path(source_rstfile)
    dest_file = source_file.with_suffix(".md")
    ctx.run(
        f"pandoc {source_file.as_posix()} -f rst -t markdown -o {dest_file.as_posix()}"
    )


@invoke.task
def generate_manual(ctx, commit=False):
    log("Generating manual from reStructuredText source...")
    ctx.run("make man")
    ctx.run("cp docs/_build/man/pipenv.1 pipenv/")
    if commit:
        log("Committing...")
        ctx.run("git add pipenv/pipenv.1")
        ctx.run('git commit -m "Update manual page."')


@invoke.task
def generate_contributing_md(ctx, commit=False):
    log("Generating CONTRIBUTING.md from reStructuredText source...")
    ctx.run("pandoc docs/dev/contributing.rst -f rst -t markdown -o CONTRIBUTING.md")
    if commit:
        log("Committing...")
        ctx.run("git add CONTRIBUTING.md")
        ctx.run('git commit -m "Update CONTRIBUTING.md."')


@invoke.task
def generate_changelog(ctx, commit=False, draft=False):
    log("Generating changelog...")
    if draft:
        commit = False
        log("Writing draft to file...")
        ctx.run("towncrier --draft > CHANGELOG.draft.md")
    else:
        ctx.run("towncrier")
    if commit:
        log("Committing...")
        ctx.run("git add CHANGELOG.md")
        ctx.run("git rm CHANGELOG.draft.md")
        ctx.run('git commit -m "Update changelog."')


@invoke.task
def clean_mdchangelog(ctx, filename=None, content=None):
    changelog = None
    if not content:
        if filename is not None:
            changelog = pathlib.Path(filename)
        else:
            changelog = _get_git_root(ctx) / "CHANGELOG.md"
        content = changelog.read_text()
    content = re.sub(
        r"([^\n]+)\n?\s+\[[\\]+(#\d+)\]\(https://github\.com/pypa/[\w\-]+/issues/\d+\)",
        r"\1 \2",
        content,
        flags=re.MULTILINE,
    )
    if changelog:
        changelog.write_text(content)
    else:
        return content


@invoke.task
def tag_version(ctx, push=False):
    version = find_version(ctx)
    version = semver.VersionInfo.parse(version)
    log(f"Tagging revision: v{version}")
    ctx.run(f"git tag v{version}")
    if push:
        log("Pushing tags...")
        ctx.run("git push origin master")
        ctx.run("git push --tags")


def add_one_day(dt):
    return dt + datetime.timedelta(days=1)


def date_offset(dt, month_offset=0, day_offset=0, truncate=False):
    new_month = (dt.month + month_offset) % 12
    year_offset = new_month // 12
    replace_args = {
        "month": dt.month + month_offset,
        "year": dt.year + year_offset,
    }
    log(
        "Getting updated date from date: {} using month offset: {} and year offset {}".format(
            dt, new_month, replace_args["year"]
        )
    )
    if day_offset:
        dt = dt + datetime.timedelta(days=day_offset)
        log(f"updated date using day offset: {day_offset} => {dt}")
    if truncate:
        log("Truncating...")
        replace_args["day"] = 1
    return dt.replace(**replace_args)


@invoke.task
def bump_version(
    ctx, dry_run=False, pre=False, dev=False, minor=False, major=False, patch=False
):
    version = find_version(ctx)
    current_version = semver.VersionInfo.parse(version)

    # Prompt the user for version change type
    if not minor and not major and not patch:
        while True:
            change_type = input(
                "Enter the version change type (major/minor/patch): "
            ).lower()
            if change_type in ["major", "minor", "patch"]:
                break
            print("Invalid input. Please enter 'major', 'minor', or 'patch'.")

    if minor:
        change_type = "minor"
    if major:
        change_type = "major"
    if patch:
        change_type = "patch"

    # Bump the version based on the user input
    if change_type == "major":
        new_version = current_version.bump_major()
    elif change_type == "minor":
        new_version = current_version.bump_minor()
    else:
        new_version = current_version.bump_patch()
    # Pre-release handling code
    if pre:
        new_version = new_version.bump_prerelease()
    if dev:
        new_version = new_version.bump_prerelease("dev")

    # Update the version file
    log(f"Found current version: {version}")
    log(f"Updating version to {new_version}")

    if dry_run:
        sys.exit(0)
    else:
        log(f"Updating to: {new_version}")
        version_file = get_version_file(ctx)
        file_contents = version_file.read_text()
        version_file.write_text(file_contents.replace(version, str(new_version)))
        ctx.run(f"git add {version_file.as_posix()}")
        log("Committing...")
        ctx.run(f'git commit -s -m "Bumped version to {new_version}."')
    return str(new_version)
