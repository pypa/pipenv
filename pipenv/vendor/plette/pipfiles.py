import hashlib
import json

from dataclasses import dataclass, asdict

from typing import Optional

from pipenv.vendor import tomlkit


from .models import (
    BaseModel,
    Hash, Requires, PipfileSection, Pipenv,
    PackageCollection, ScriptCollection, SourceCollection,
    remove_empty_values
)


PIPFILE_SECTIONS = {
    "sources": SourceCollection,
    "packages": PackageCollection,
    "dev-packages": PackageCollection,
    "requires": Requires,
    "scripts": ScriptCollection,
    "pipfile":  PipfileSection,
    "pipenv": Pipenv
}

DEFAULT_SOURCE_TOML = """\
[[source]]
name = "pypi"
url = "https://pypi.org/simple"
verify_ssl = true
"""


@dataclass
class Pipfile(BaseModel):
    """Representation of a Pipfile."""
    sources: SourceCollection
    packages: Optional[PackageCollection] = None
    packages: Optional[PackageCollection] = None
    dev_packages: Optional[PackageCollection] = None
    requires: Optional[Requires] = None
    scripts: Optional[ScriptCollection] = None
    pipfile: Optional[PipfileSection] = None
    pipenv: Optional[Pipenv] = None

    def validate_sources(self, value):
        if isinstance(value, list):
            return SourceCollection(value)
        return SourceCollection(value.value)

    def validate_pipenv(self, value):
        if value is not None:
            return Pipenv(**value)
        return value

    def validate_packages(self, value):
        PackageCollection(value)
        return value

    def to_dict(self):
        data = {
            "_meta": {
                "requires": getattr(self, "requires", {}),
            },
        }

        for section in ("develop", "default"):
            obj = getattr(self, section, {})
            if obj:
                data[section] = obj.to_dict()
            else:
                data[section] = obj

        data["_meta"].update(asdict(getattr(self, "sources", {})))

        for category, values in self.__dict__.items():
            if category in PIPFILE_SECTIONS or category in (
                    "default", "develop", "pipenv"):
                continue

            if hasattr(values, "to_dict"):
                values = values.to_dict()

            data[category] = values

        remove_empty_values(data)

        return data

    def get_hash(self):
        data = self.to_dict()
        content = json.dumps(data, sort_keys=True, separators=(",", ":"))
        if isinstance(content, str):
            content = content.encode("utf-8")
        return Hash.from_hash(hashlib.sha256(content))

    @classmethod
    def load(cls, f, encoding=None):
        content = f.read()
        if encoding is not None:
            content = content.decode(encoding)
        data = tomlkit.loads(content)
        if "source" not in data:
            # HACK: There is no good way to prepend a section to an existing
            # TOML document, but there's no good way to copy non-structural
            # content from one TOML document to another either. Modify the
            # TOML content directly, and load the new in-memory document.
            sep = "" if content.startswith("\n") else "\n"
            content = DEFAULT_SOURCE_TOML + sep + content
        data["sources"] = data.pop("source")
        packages_sections = {}
        data_sections = list(data.keys())
        for k in data_sections:
            if k not in cls.__dataclass_fields__:
                packages_sections[k] = data.pop(k)

        inst = cls(**data)
        if packages_sections:
            for k, v in packages_sections.items():
                setattr(inst, k, PackageCollection(v))
        return inst

    @property
    def source(self):
        return self.sources

    def dump(self, f, encoding=None):
        data = self.to_dict()
        new_data = {}
        metadata = data.pop("_meta")
        new_data["source"] = metadata.pop("sources")
        new_data["packages"] = data.pop("default")
        new_data.update(data)
        content = tomlkit.dumps(new_data)

        if encoding is not None:
            content = content.encode(encoding)
        f.write(content)

    def __getattr__(self, key):

        item = getattr(self.__dict__, key)
        if hasattr(item, "to_dict"):
            return item.to_dict()
        return item
