from pip._vendor.packaging.version import Version


def match_version(target, candidate):
    target_release = target._key[1]
    return (
        isinstance(candidate, Version) and
        not candidate.is_prerelease and
        candidate._key[1][:len(target_release)] == target_release
    )
