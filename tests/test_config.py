import copy
import json

import pytest

from tests.test_cli import BUNDLE
from traffic_complaint_form.config import ERROR, BundleError, FilingConfig


def test_complete_bundle_and_safe_repr():
    config = FilingConfig.from_env({"FILING_BUNDLE": json.dumps(BUNDLE)})
    assert config.complainant.id_number == BUNDLE["complainant"]["id_number"]
    assert BUNDLE["pdf_password"] not in repr(config)


@pytest.mark.parametrize("key", list(BUNDLE))
def test_every_root_key_required(key):
    bundle = copy.deepcopy(BUNDLE)
    del bundle[key]
    with pytest.raises(BundleError, match="FILING_BUNDLE"):
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})


@pytest.mark.parametrize("section", ["complainant", "delivery"])
def test_every_nested_key_required(section):
    for key in BUNDLE[section]:
        bundle = copy.deepcopy(BUNDLE)
        del bundle[section][key]
        with pytest.raises(BundleError):
            FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})


@pytest.mark.parametrize(
    "path,value",
    [
        (("version",), True),
        (("version",), 2),
        (("pdf_password",), "short"),
        (("pdf_password",), "x" * 128),
        (("pdf_password",), "x\n" * 20),
        (("complainant", "id_number"), "000000001"),
        (("complainant", "first_name"), 1),
        (("delivery", "smtp_port"), True),
        (("delivery", "smtp_port"), 0),
        (("delivery", "smtp_port"), "587"),
        (("delivery", "recipient_email"), "not-an-email"),
        (("delivery", "smtp_from"), "a@example.com\nBcc:bad@example.com"),
        (("delivery", "smtp_username"), ""),
        (("delivery", "smtp_app_password"), None),
    ],
)
def test_strict_schema_never_echoes_invalid_data(path, value):
    bundle = copy.deepcopy(BUNDLE)
    target = bundle
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})
    assert str(error.value) == ERROR


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        '"value"',
        "not-json-secret",
        '{"version":1,"version":1}',
        '{"attacker-private-field":1}',
        "x" * 50000,
    ],
)
def test_malformed_duplicate_and_unknown_fields_fail_closed(raw):
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": raw})
    assert str(error.value) == ERROR
