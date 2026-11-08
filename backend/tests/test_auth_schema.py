from jsonschema import Draft7Validator

from config.openapi import inject_contract


def _response_validator(path):
    contract = inject_contract({}, None, None, True)
    schema = contract["paths"][path]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    return Draft7Validator({**schema, "components": contract["components"]})


def test_login_contract_accepts_password_session_and_bound_totp_challenge():
    contract = inject_contract({}, None, None, True)
    validator = _response_validator("/api/v1/auth/login")
    password_session = {
        "authenticated": True,
        "mfa_required": False,
        "mfa_enabled": False,
        "totp_setup_required": False,
        "expires_at": "2030-01-01T00:00:00Z",
        "admin": {"username": "owner"},
    }
    challenge = {
        "challenge_id": "826515f3-08cb-43cb-a47a-4705cae56e18",
        "mfa_required": True,
        "totp_setup_required": False,
        "expires_at": "2030-01-01T00:00:00Z",
    }
    assert list(validator.iter_errors(password_session)) == []
    assert list(validator.iter_errors(challenge)) == []
    assert list(validator.iter_errors({"mfa_required": False}))
    session_schema = contract["components"]["schemas"]["AdminSession"]
    assert "mfa_enabled" in session_schema["required"]


def test_optional_enrollment_contract_exposes_bound_challenge_and_password_step_up():
    contract = inject_contract({}, None, None, True)
    assert contract["paths"]["/api/v1/auth/totp/setup"]["post"]["security"] == [
        {"cookieAuth": []}
    ]
    setup = _response_validator("/api/v1/auth/totp/setup")
    assert not list(
        setup.iter_errors(
            {
                "challenge_id": "826515f3-08cb-43cb-a47a-4705cae56e18",
                "secret": "test-only-placeholder",
                "otpauth_uri": "test-only-placeholder",
                "expires_at": "2030-01-01T00:00:00Z",
            }
        )
    )
    request = contract["paths"]["/api/v1/auth/step-up"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    validator = Draft7Validator({**request, "components": contract["components"]})
    assert not list(validator.iter_errors({"password": "test-only-password"}))
    assert list(validator.iter_errors({"code": "123456"}))
