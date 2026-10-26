import pytest

from traffic_complaint_form.crypto import (
    CaseDecryptionError,
    decrypt_payload,
    encrypt_payload,
    generate_keypair,
)


def test_roundtrip():
    public_b64, private_b64 = generate_keypair()
    payload = b'{"vehicle_number": "12-345-67"}'
    ciphertext = encrypt_payload(public_b64, payload)
    assert payload not in ciphertext.encode()  # ciphertext hides the data
    assert decrypt_payload(private_b64, ciphertext) == payload


def test_wrong_key_fails():
    public_b64, _ = generate_keypair()
    _, other_private_b64 = generate_keypair()
    ciphertext = encrypt_payload(public_b64, b"{}")
    with pytest.raises(CaseDecryptionError):
        decrypt_payload(other_private_b64, ciphertext)


def test_encrypt_case_cli(tmp_path, capsys):
    from traffic_complaint_form.crypto import encrypt_case_main

    public_b64, private_b64 = generate_keypair()
    pub = tmp_path / "pub.key"
    pub.write_text(public_b64)
    src = tmp_path / "case.json"
    src.write_text('{"vehicle_number": "1"}')
    out = tmp_path / "case.enc"
    assert encrypt_case_main(["--in", str(src), "--out", str(out), "--public-key", str(pub)]) == 0
    assert decrypt_payload(private_b64, out.read_text()) == b'{"vehicle_number": "1"}'
