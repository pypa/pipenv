import collections
import io
import os
from typing import Optional, Any

from pipenv.vendor.pydantic import BaseModel
from pipenv.patched.pip._vendor.packaging.markers import Marker

SectionDifference = collections.namedtuple("SectionDifference", ["inthis", "inthat"])
FileDifference = collections.namedtuple("FileDifference", ["default", "develop"])


def _are_pipfile_entries_equal(a, b):
    a = {k: v for k, v in a.items() if k not in ("markers", "hashes", "hash")}
    b = {k: v for k, v in b.items() if k not in ("markers", "hashes", "hash")}
    if a != b:
        return False
    try:
        marker_eval_a = Marker(a["markers"]).evaluate()
    except (AttributeError, KeyError, TypeError, ValueError):
        marker_eval_a = True
    try:
        marker_eval_b = Marker(b["markers"]).evaluate()
    except (AttributeError, KeyError, TypeError, ValueError):
        marker_eval_b = True
    return marker_eval_a == marker_eval_b


DEFAULT_NEWLINES = "\n"


def preferred_newlines(f):
    if isinstance(f.newlines, str):
        return f.newlines
    return DEFAULT_NEWLINES


class ProjectFile(BaseModel):
    location: str
    line_ending: str
    model: Optional[Any] = {}

    @classmethod
    def read(cls, location: str, model_cls, invalid_ok: bool = False) -> "ProjectFile":
        if not os.path.exists(location) and not invalid_ok:
            raise FileNotFoundError(location)
        try:
            with io.open(location, encoding="utf-8") as f:
                content = f.read()
                model = model_cls.parse_raw(content)
                line_ending = preferred_newlines(f)
        except Exception:
            if not invalid_ok:
                raise
            model = None
            line_ending = DEFAULT_NEWLINES
        return cls(location=location, line_ending=line_ending, model=model)

    def write(self) -> None:
        kwargs = {"encoding": "utf-8", "newline": self.line_ending}
        with io.open(self.location, "w", **kwargs) as f:
            if self.model:
                f.write(self.model.json())

    def dumps(self) -> str:
        if self.model:
            return self.model.json()
        else:
            return ""
