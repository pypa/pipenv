from pipenv._compat import TemporaryDirectory
import invoke


from . import _get_git_root, _get_vendor_dir, log


@invoke.task
def vendor_passa(ctx):
    with TemporaryDirectory(prefix='passa') as passa_dir:
        vendor_dir = _get_vendor_dir(ctx).absolute().as_posix()
        ctx.run("git clone https://github.com/sarugaku/passa.git {0}".format(passa_dir.name))
        with ctx.cd("{0}".format(passa_dir.name)):
            # ctx.run("git checkout 0.3.0")
            ctx.run("pip install plette[validation] requirementslib distlib pip-shims -q --exists-action=i")
            log("Packing Passa")
            ctx.run("invoke pack")
            log("Moving pack to vendor dir!")
            ctx.run("mv pack/passa.zip {0}".format(vendor_dir))
    log("Successfully vendored passa!")
