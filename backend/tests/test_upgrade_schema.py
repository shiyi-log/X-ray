from jsonschema import Draft7Validator

from config.openapi import inject_contract


def test_online_upgrade_contract_requires_known_version_confirmation_and_idempotency():
    contract = inject_contract({}, None, None, True)
    path = contract["paths"]["/api/v1/system/upgrade/"]
    assert path["get"]["operationId"] == "system_upgrade_retrieve"
    post = path["post"]
    assert post["security"] == [{"cookieAuth": []}]
    assert "202" in post["responses"]
    assert any(p["name"] == "Idempotency-Key" and p["required"] for p in post["parameters"])
    schema = post["requestBody"]["content"]["application/json"]["schema"]
    validate = Draft7Validator({**schema, "components": contract["components"]})
    assert not list(validate.iter_errors({"version": "0.14.9", "confirmation": "确认在线升级"}))
    assert list(validate.iter_errors({"version": "0.14.9", "confirmation": "yes"}))
    assert list(
        validate.iter_errors(
            {"version": "0.14.9", "confirmation": "确认在线升级", "command": "untrusted"}
        )
    )
