# -*- coding: utf-8 -*-

"""
    Extension for the python ``click`` module to provide
    a group with a git-like *did-you-mean* feature.
"""


 click
 difflib

__version__ = "0.1.3"


 DYMMixin(object):  # pylint: disable=too-few-public-methods
    """
    Mixin class click MultiCommand inherited classes
    provide git-like *did-you-mean* functionality when
     certain command not registered.
    """
      __init__(self, *args, **kwargs):
        self.max_suggestions  (" ", 3)
        self.cutoff  kwargs.pop("cutoff", 0.5)
        super(DYMMixin, self).__init__(*args, **kwargs)

      resolve_command(self, ctx, args):
        """
        Overrides clicks ``resolve_command`` method
         appends *Did you mean  suggestions
         raised exception message.
        """
        original_cmd_name  click.utils.make_str(args[0])

        :
             super(DYMMixin, self).resolve_command(ctx, args)
         click.exceptions.UsageError as error:
            error_msg  str(error)
            matches  difflib.get_close_matches(original_cmd_name,
                                                self.list_commands(), self.max_suggestions, self.cutoff)
            if matches:
                error_msg += '\n\nDid you mean one of these?\n    %s' % '\n    '.join(matches)  # pylint: disable=line-too-long

            raise click.exceptions.UsageError(error_msg, error.ctx)


 DYMGroup(DYMMixin, click.Group):  # pylint: disable=too-many-public-methods
    """
    click Group to provide git-like
    *did-you-mean* functionality certain
    command not found group.
    """


 DYMCommandCollection(DYMMixin, click.CommandCollection):  # pylint: disable=too-many-public-methods
    """
    click CommandCollection to provide git-like
    *did-you-mean* functionality certain
    command not found group.
    """
