from pathlib import Path


def test_session_manager_service_locator_is_fully_removed_from_runtime_and_tests():
    matches = []
    for path in Path(".").glob("**/*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "get_session_manager_service(" in text or "set_session_manager_service(" in text:
            matches.append(path.as_posix())

    assert sorted(matches) == [
        "tests/test_no_runtime_service_locator_usage.py",
    ]
