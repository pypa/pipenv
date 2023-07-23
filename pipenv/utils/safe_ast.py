import ast
from typing import Any, List


def _find_in_call(call: ast.Call, name: str):
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _find_call_kwargs(call: ast.Call):
    kwargs = None
    for keyword in call.keywords:
        if keyword.arg is None:
            kwargs = keyword.value

    return kwargs


def _find_in_dict(dict_: ast.Dict, name: str):
    for key, val in zip(dict_.keys, dict_.values):
        if isinstance(key, ast.Str) and key.s == name:
            return val
    return None


def _find_variable_in_body(body, name: str):
    for elem in body:
        if not isinstance(elem, (ast.Assign, ast.AnnAssign)):
            continue

        if isinstance(elem, ast.AnnAssign):
            if not isinstance(elem.target, ast.Name):
                continue
            if elem.value and elem.target.id == name:
                return elem.value
        else:
            for target in elem.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == name:
                    return elem.value
    return None


def _find_single_string(call: ast.Call, body: List[Any], name: str):
    value = _find_in_call(call, name)
    if value is None:
        # Trying to find in kwargs
        kwargs = _find_call_kwargs(call)
        if kwargs is None:
            return None

        if not isinstance(kwargs, ast.Name):
            raise ValueError()

        variable = _find_variable_in_body(body, kwargs.id)
        if not isinstance(variable, (ast.Dict, ast.Call)):
            raise ValueError()

        if isinstance(variable, ast.Call):
            if not isinstance(variable.func, ast.Name):
                raise ValueError()

            if variable.func.id != "dict":
                raise ValueError()

            value = _find_in_call(variable, name)
        else:
            value = _find_in_dict(variable, name)

    if value is None:
        return None

    if isinstance(value, ast.Str):
        return value.s
    elif isinstance(value, ast.Name):
        variable = _find_variable_in_body(body, value.id)

        if variable is not None and isinstance(variable, ast.Str):
            return variable.s

    raise ValueError()


def _find_sub_setup_call(elements: List[Any]):
    for element in elements:
        if not isinstance(element, (ast.FunctionDef, ast.If)):
            continue

        setup_call = _find_setup_call(element.body)
        if setup_call != (None, None):
            setup_call, body = setup_call

            body = elements + body

            return setup_call, body

    return None, None


def _find_setup_call(elements: List[Any]):
    funcdefs = []
    for i, element in enumerate(elements):
        if isinstance(element, ast.If) and i == len(elements) - 1:
            # Checking if the last element is an if statement
            # and if it is 'if __name__ == "__main__"' which
            # could contain the call to setup()
            test = element.test
            if not isinstance(test, ast.Compare):
                continue

            left = test.left
            if not isinstance(left, ast.Name):
                continue

            if left.id != "__name__":
                continue

            setup_call, body = _find_sub_setup_call([element])
            if not setup_call:
                continue

            return setup_call, body + elements
        if not isinstance(element, ast.Expr):
            if isinstance(element, ast.FunctionDef):
                funcdefs.append(element)

            continue

        value = element.value
        if not isinstance(value, ast.Call):
            continue

        func = value.func
        if not (isinstance(func, ast.Name) and func.id == "setup") and not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "setuptools"
            and func.attr == "setup"
        ):
            continue

        return value, elements

    # Nothing, we inspect the function definitions
    return _find_sub_setup_call(funcdefs)
