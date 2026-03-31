import importlib
import sys
import types


def _install_aiohttp_stub() -> None:
    aiohttp_module = types.ModuleType("aiohttp")
    aiohttp_module.web = types.SimpleNamespace(
        Application=type("Application", (), {}),
        Request=type("Request", (), {}),
        Response=type("Response", (), {}),
        AppRunner=type("AppRunner", (), {}),
        TCPSite=type("TCPSite", (), {}),
        json_response=lambda *args, **kwargs: None,
        middleware=lambda fn: fn,
    )
    sys.modules.setdefault("aiohttp", aiohttp_module)


def test_service_no_longer_exports_legacy_session_manager_locator_symbols():
    sys.modules.pop("service", None)
    _install_aiohttp_stub()

    service = importlib.import_module("service")

    assert not hasattr(service, "get_session_manager_service")
    assert not hasattr(service, "set_session_manager_service")
