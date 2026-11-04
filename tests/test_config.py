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
    assert str(error.value).startswith(ERROR)


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
    assert str(error.value).startswith(ERROR)


def test_diagnostic_code_cannot_echo_arbitrary_value():
    assert BundleError("private-canary").code == "schema"
    assert "private-canary" not in str(BundleError("private-canary"))


def test_known_field_diagnostic_and_no_values():
    bundle = copy.deepcopy(BUNDLE)
    bundle["pdf_password"] = "private-short"  # noqa: S105 - invented validation fixture
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})
    assert error.value.code == "pdf_password"
    assert "private-short" not in str(error.value)


BUNDLE_V2 = {
    **{k: v for k, v in BUNDLE.items() if k != "version"},
    "version": 2,
    "archive_password": "invented-archive-password",
    "archive_format": "zip-aes",
}


def test_v2_bundle_parses_archive_fields_and_safe_repr():
    config = FilingConfig.from_env({"FILING_BUNDLE": json.dumps(BUNDLE_V2)})
    assert config.archive_password == BUNDLE_V2["archive_password"]
    assert config.archive_format == "zip-aes"
    assert BUNDLE_V2["archive_password"] not in repr(config)


def test_v2_archive_format_defaults_to_zip_legacy():
    bundle = {k: v for k, v in BUNDLE_V2.items() if k != "archive_format"}
    config = FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})
    assert config.archive_format == "zip-legacy"


def test_v1_bundle_still_valid_for_single_mode():
    config = FilingConfig.from_env({"FILING_BUNDLE": json.dumps(BUNDLE)})
    assert config.archive_password is None
    assert config.archive_format == "zip-legacy"


def test_v1_bundle_fails_closed_for_batch():
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(BUNDLE)}, require_archive=True)
    assert error.value.code == "archive_password"


@pytest.mark.parametrize(
    "path,value,code",
    [
        (("archive_password",), "short", "archive_password"),
        (("archive_password",), "x" * 128, "archive_password"),
        (("archive_password",), "x\n" * 20, "archive_password"),
        (("archive_password",), "invented-test-password-only", "archive_password"),  # equals pdf_password
        (("archive_password",), "123456782", "archive_password"),  # equals ID (too short anyway)
        (("archive_format",), "7z", "archive_format"),
        (("archive_format",), "", "archive_format"),
        (("archive_format",), 1, "archive_format"),
    ],
)
def test_v2_archive_fields_rejected_without_echo(path, value, code):
    bundle = copy.deepcopy(BUNDLE_V2)
    target = bundle
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})
    assert error.value.code == code
    if str(value):
        assert str(value) not in str(error.value)


def test_v2_missing_archive_password_rejected():
    bundle = {k: v for k, v in BUNDLE_V2.items() if k != "archive_password"}
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})
    assert error.value.code == "root"


def test_v1_with_archive_keys_rejected_as_unknown():
    bundle = {**BUNDLE, "archive_password": "invented-archive-password"}
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})
    assert error.value.code == "root"
