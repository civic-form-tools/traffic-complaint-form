import pytest

from traffic_complaint_form.models import Complainant

# Invented fixture identity only - never real personal data (see docs/SECRETS.md).
TEST_ID_PLACEHOLDER = "123456782"


@pytest.fixture()
def complainant() -> Complainant:
    return Complainant(
        first_name="משה",
        last_name="כהן",
        id_number=TEST_ID_PLACEHOLDER,
        address="רחוב הדוגמה 1, ירושלים",
        phone="050-0000000",
    )
