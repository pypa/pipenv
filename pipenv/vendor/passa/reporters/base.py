# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import resolvelib


class ResolveLibReporter(resolvelib.BaseReporter):
    """Implementation of a ResolveLib reporter that bridge messages.
    """
    def __init__(self, parent):
        super(ResolveLibReporter, self).__init__()
        self.parent = parent

    def starting(self):
        self.parent.report("resolvelib-starting", {"child": self})

    def ending_round(self, index, state):
        self.parent.report("resolvelib-ending-round", {
            "child": self, "index": index, "state": state,
        })

    def ending(self, state):
        self.parent.report("resolvelib-ending", {
            "child": self, "state": state,
        })


class BaseReporter(object):
    """Basic reporter that does nothing.
    """
    def build_for_resolvelib(self):
        """Build a reporter for ResolveLib.
        """
        return ResolveLibReporter(self)

    def report(self, event, context):
        """Report an event.

        The default behavior is to look for a "handle_EVENT" method on the
        class to execute, or do nothing if there is no such method.

        :param event: A string to indicate the event.
        :param context: A mapping containing appropriate data for the handling
            function.
        """
        handler_name = "handle_{}".format(event.replace("-", "_"))
        try:
            handler = getattr(self, handler_name)
        except AttributeError:
            return
        handler(context or {})
