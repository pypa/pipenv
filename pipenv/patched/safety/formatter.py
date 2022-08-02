import logging
from abc import ABCMeta, abstractmethod

NOT_IMPLEMENTED = "You should implement this."

LOG = logging.getLogger(__name__)


class FormatterAPI:
    """
    Strategy Abstract class, with all the render methods that the concrete implementations should support
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def render_vulnerabilities(self, announcements, vulnerabilities, remediations, full, packages):
        raise NotImplementedError(NOT_IMPLEMENTED)  # pragma: no cover

    @abstractmethod
    def render_licenses(self, announcements, licenses):
        raise NotImplementedError(NOT_IMPLEMENTED)  # pragma: no cover

    @abstractmethod
    def render_announcements(self, announcements):
        raise NotImplementedError(NOT_IMPLEMENTED)  # pragma: no cover


class SafetyFormatter(FormatterAPI):

    def render_vulnerabilities(self, announcements, vulnerabilities, remediations, full, packages):
        LOG.info('Safety is going to render_vulnerabilities with format: %s', self.format)
        return self.format.render_vulnerabilities(announcements, vulnerabilities, remediations, full, packages)

    def render_licenses(self, announcements, licenses):
        LOG.info('Safety is going to render_licenses with format: %s', self.format)
        return self.format.render_licenses(announcements, licenses)

    def render_announcements(self, announcements):
        LOG.info('Safety is going to render_announcements with format: %s', self.format)
        return self.format.render_announcements(announcements)

    def __init__(self, output):
        from pipenv.patched.safety.formatters.screen import ScreenReport
        from pipenv.patched.safety.formatters.text import TextReport
        from pipenv.patched.safety.formatters.json import JsonReport
        from pipenv.patched.safety.formatters.bare import BareReport

        self.format = ScreenReport()

        if output == 'json':
            self.format = JsonReport()
        elif output == 'bare':
            self.format = BareReport()
        elif output == 'text':
            self.format = TextReport()
