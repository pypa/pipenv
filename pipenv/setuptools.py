import json


def find_requirements(lockfile_path: str = "Pipfile.lock"):
    with open(lockfile_path) as lockfile:
        requirements: dict[str, dict] = json.load(lockfile)["default"]
        return [name + info["version"] for name, info in requirements.items()]
