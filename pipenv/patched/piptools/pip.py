import optparse

from ._compat import Command, cmdoptions


class PipCommand(Command):
    name = 'PipCommand'


def get_pip_command():
    # Use pip's parser for pip.conf management and defaults.
    # General options (find_links, index_url, extra_index_url, trusted_host,
    # and pre) are defered to pip.
    pip_command = PipCommand()
    pip_command.parser.add_option(cmdoptions.no_binary())
    pip_command.parser.add_option(cmdoptions.only_binary())
    index_opts = cmdoptions.make_option_group(
        cmdoptions.index_group,
        pip_command.parser,
    )
    pip_command.parser.insert_option_group(0, index_opts)
    pip_command.parser.add_option(optparse.Option('--pre', action='store_true', default=False))

    return pip_command


pip_command = get_pip_command()

# Get default values of the pip's options (including options from pipenv.patched.notpip.conf).
pip_defaults = pip_command.parser.get_default_values()
