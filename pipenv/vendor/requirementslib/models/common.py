from typing import Any, Dict

from pipenv.vendor.pydantic import BaseModel, Extra


class ReqLibBaseModel(BaseModel):
    def __setattr__(self, name, value):  # noqa: C901 (ignore complexity)
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

    def dict(self, *args, **kwargs) -> Dict[str, Any]:
        """The requirementslib classes make use of a lot of private attributes
        which do not get serialized out to the dict by default in pydantic."""
        model_dict = super().dict(*args, **kwargs)
        private_attrs = {k: v for k, v in self.__dict__.items() if k.startswith("_")}
        model_dict.update(private_attrs)
        return model_dict
