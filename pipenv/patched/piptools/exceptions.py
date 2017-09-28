class PipToolsError(Exception):
    pass


class NoCandidateFound(PipToolsError):
    def __init__(self, ireq, candidates_tried):
        self.ireq = ireq
        self.candidates_tried = candidates_tried

    def __str__(self):
        sorted_versions = sorted(c.version for c in self.candidates_tried)
        lines = [
            'Could not find a version that matches {}'.format(self.ireq),
            'Tried: {}'.format(', '.join(str(version) for version in sorted_versions) or '(no version found at all)')
        ]
        return '\n'.join(lines)


class UnsupportedConstraint(PipToolsError):
    def __init__(self, message, constraint):
        super(UnsupportedConstraint, self).__init__(message)
        self.constraint = constraint

    def __str__(self):
        message = super(UnsupportedConstraint, self).__str__()
        return '{} (constraint was: {})'.format(message, str(self.constraint))


class IncompatibleRequirements(PipToolsError):
    def __init__(self, ireq_a, ireq_b):
        self.ireq_a = ireq_a
        self.ireq_b = ireq_b

    def __str__(self):
        message = "Incompatible requirements found: {} and {}"
        return message.format(self.ireq_a, self.ireq_b)
