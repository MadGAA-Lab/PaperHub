from paperhub.settings_registry import coerce_value, field_by_key


def test_update_check_field_exists_and_defaults_on() -> None:
    field = field_by_key("PAPERHUB_UPDATE_CHECK")
    assert field is not None
    assert field.type == "bool"
    assert field.default == "1"


def test_update_check_coerces_bool() -> None:
    field = field_by_key("PAPERHUB_UPDATE_CHECK")
    assert field is not None
    assert coerce_value(field, "off") == "0"
    assert coerce_value(field, "true") == "1"
