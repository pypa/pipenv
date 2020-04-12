class PipToolsError(Exception):
    pass


class NoCandidateFound(PipToolsError):
    def __init__(self, ireq, candidates_tried, finder):
        self.ireq = ireq
        self.candidates_tried = candidates_tried
        self.finder = finder

    def __str__(self):
        versions = []
        pre_versions = []

        for candidate in sorted(self.candidates_tried):
            version = str(candidate.version)
            if candidate.version.is_prerelease:
                pre_versions.append(version)
            else:
                versions.append(version)

        lines = ["Could not find a version that matches {}".format(self.ireq)]

        if versions:
            lines.append("Tried: {}".format(", ".join(versions)))

        if pre_versions:
            if self.finder.allow_all_prereleases:
                line = "Tried"
            else:
                line = "Skipped"

            line += " pre-versions: {}".format(", ".join(pre_versions))
            lines.append(line)

        if versions or pre_versions:
            lines.append(
                "There are incompatible versions in the resolved dependencies:"
            )
            source_ireqs = getattr(self.ireq, "_source_ireqs", [])
            lines.extend("  {}".format(ireq) for ireq in source_ireqs)
        else:
            lines.append("No versions found")
            lines.append(
                "{} {} reachable?".format(
                    "Were" if len(self.finder.index_urls) > 1 else "Was",
                    " or ".join(self.finder.index_urls),
                )
            )
        return "\n".join(lines)


class IncompatibleRequirements(PipToolsError):
    def __init__(self, ireq_a, ireq_b):
        self.ireq_a = ireq_a
        self.ireq_b = ireq_b

    def __str__(self):
        message = "Incompatible requirements found: {} and {}"
        return message.format(self.ireq_a, self.ireq_b)
