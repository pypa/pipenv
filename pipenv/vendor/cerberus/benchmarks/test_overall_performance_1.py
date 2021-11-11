"""
some notes regarding this test suite:
- results are only comparable using the semantically equal schema against and
  identical set of documents in the same execution environment
- the module can be executed to generate a new set of test documents
- it is intended to detect *significant* changes in validation time
- benchmarks should run with as few other processes running on the system as
  possible (e.g. an Alpine Linux on bare metal w/o a Desktop environment)
"""

import json
from collections import Counter
from pathlib import Path
from random import choice, randrange
from typing import Callable, List

from pytest import mark

from pipenv.vendor.cerberus import rules_set_registry, schema_registry, TypeDefinition, Validator
from pipenv.vendor.cerberus.benchmarks import DOCUMENTS_PATH


rules_set_registry.add("path_rules", {"coerce": Path, "type": "path"})


schema_registry.add(
    "field_3_schema",
    {
        # an outer rule requires all fields' values to be a list
        "field_31": {"contains": 0, "empty": False},
        "field_32": {
            "default": [None, None, None],
            "items": [
                {"type": "integer"},
                {"type": "string"},
                {"type": ["integer", "string"]},
            ],
            "schema": {"nullable": True},
        },
    },
)


def schema_1_field_3_allow_unknown_check_with(field, value, error):
    if len(value) > 9:
        error(field, "Requires a smaller list.")


schema_1 = {
    "field_1": {
        "type": "dict",
        "required": True,
        "allow_unknown": True,
        "keysrules": {"regex": r"field_1[12345]"},
        "minlength": 3,
        "maxlength": 5,
        "schema": {
            "field_11": {
                "type": "integer",
                "allowed": list(range(100)),
                "dependencies": {"field_12": 0, "^field_1.field_13": 0},
            },
            "field_12": {
                "type": "integer",
                "default_setter": lambda _: 1,
                "forbidden": (1,),
            },
            "field_13": {"type": "integer"},
            "field_14": {"rename": "field_13"},
        },
    },
    "field_2": {
        "type": "dict",
        "allow_unknown": False,
        "schema": {
            "field_21": {
                "type": "integer",
                "coerce": [str.strip, int],
                "min": 9,
                "max": 89,
                "anyof": [{"dependencies": "field_22"}, {"dependencies": "field_23"}],
            },
            "field_22": {"excludes": "field_23", "nullable": True},
            "field_23": {"nullable": True},
        },
    },
    "field_3": {
        "allow_unknown": {"check_with": schema_1_field_3_allow_unknown_check_with},
        "valuesrules": {"type": "list"},
        "require_all": True,
        "schema": "field_3_schema",
    },
    "field_4": "path_rules",
}


def init_validator():
    class TestValidator(Validator):
        types_mapping = {
            **Validator.types_mapping,
            "path": TypeDefinition("path", (Path,), ()),
        }

    return TestValidator(schema_1, purge_unknown=True)


def load_documents():
    with (DOCUMENTS_PATH / "overall_documents_1.json").open() as f:
        documents = json.load(f)
    return documents


def validate_documents(init_validator: Callable, documents: List[dict]):
    doc_count = failed_count = 0
    error_paths = Counter()
    validator = init_validator()

    def count_errors(errors):
        if errors is None:
            return
        for error in errors:
            if error.is_group_error:
                count_errors(error.child_errors)
            else:
                error_paths[error.schema_path] += 1

    for document in documents:
        if validator.validated(document) is None:
            failed_count += 1
            count_errors(validator._errors)
        doc_count += 1

    print(
        f"{failed_count} out of {doc_count} documents failed with "
        f"{len(error_paths)} different error leafs."
    )
    print("Top 3 errors, excluding container errors:")
    for path, count in error_paths.most_common(3):
        print(f"{count}: {path}")


@mark.benchmark(group="overall-1")
def test_overall_performance_1(benchmark):
    benchmark.pedantic(validate_documents, (init_validator, load_documents()), rounds=5)


#


def generate_sample_document_1() -> dict:
    result = {}
    for i in (1, 2, 3, 4, 5):
        if randrange(100):
            result[f"field_{i}"] = globals()[f"generate_document_1_field_{i}"]()
    return result


def generate_document_1_field_1() -> dict:
    result = {"field_11": randrange(100), "field_13": 0}
    if randrange(100):
        result["field_12"] = 0
    if not randrange(100):
        result["field_14"] = None
    if randrange(100):
        result["field_15"] = None
    return result


def generate_document_1_field_2() -> dict:
    x = "*" if not randrange(50) else " "
    result = {"field_21": x + str(randrange(100)) + x}

    if randrange(100):
        result["field_22"] = None
    if "field_22" in result and not randrange(100):
        result["field_23"] = None

    return result


def generate_document_1_field_3() -> dict:
    result = {}
    if randrange(100):
        result["field_31"] = [randrange(2) for _ in range(randrange(20))]
    else:
        result["field_31"] = None
    if randrange(100):
        result["field_32"] = [
            choice((0, 0, 0, 0, 0, 0, 0, 0, "", None)),
            choice(("", "", "", "", "", "", "", "", 0, None)),
            choice((0, 0, 0, 0, "", "", "", "", None)),
        ]
    if not randrange(10):
        result["3_unknown"] = [0] * (randrange(10) + 1)
    return result


def generate_document_1_field_4():
    return "/foo/bar" if randrange(100) else 0


def generate_document_1_field_5():
    return None


def write_sample_documents():
    with (DOCUMENTS_PATH / "overall_documents_1.json").open("wt") as f:
        json.dump([generate_sample_document_1() for _ in range(10_000)], f)


if __name__ == "__main__":
    write_sample_documents()
