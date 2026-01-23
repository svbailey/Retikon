from retikon_core.storage.validate_graphar import validate_all


def test_graphar_yaml_validation():
    errors = validate_all()
    assert errors == []
