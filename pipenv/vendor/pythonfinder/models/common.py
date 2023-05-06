from __future__ import annotations

from pipenv.vendor.pydantic import BaseModel, Extra


class FinderBaseModel(BaseModel):
    def __setattr__(self, name, value):
        private_attributes = {
            field_name
            for field_name in self.__annotations__
            if field_name.startswith("_")
        }

        if name in private_attributes or name in self.__fields__:
            return object.__setattr__(self, name, value)

        if self.__config__.extra is not Extra.allow and name not in self.__fields__:
            raise ValueError(f'"{self.__class__.__name__}" object has no field "{name}"')

        object.__setattr__(self, name, value)

    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        allow_mutation = True
        include_private_attributes = False
