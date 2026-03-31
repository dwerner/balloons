import ast
import importlib
import sys
import types
from pathlib import Path


RUNTIME_EXPORTS = {
    "WsServer",
    "QueueStateService",
    "SessionManagerService",
    "GoalTreeStateService",
    "TaskStateService",
    "SessionDataService",
    "ImageService",
    "SoundService",
    "DebugLogService",
    "FileStateService",
    "KanbanWebSocketService",
    "UserAuthService",
    "get_user_storage",
    "create_http_auth_server",
    "SupervisorStateService",
    "LSPService",
}

RUNTIME_MODULES = {
    "headless": Path("headless.py"),
    "service.ws_server": Path("service/ws_server.py"),
    "plugins.integration": Path("plugins/integration.py"),
    "plugins.rpc_service": Path("plugins/rpc_service.py"),
    "plugins.registry": Path("plugins/registry.py"),
}


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
    sys.modules["aiohttp"] = aiohttp_module



def _clear_service_modules() -> None:
    for name in list(sys.modules):
        if name == "service" or name.startswith("service."):
            sys.modules.pop(name, None)



def _runtime_from_service_contracts() -> dict[str, set[str]]:
    contracts: dict[str, set[str]] = {}

    for module_name, file_path in RUNTIME_MODULES.items():
        tree = ast.parse(file_path.read_text(), filename=str(file_path))
        imported_names: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "service":
                imported_names.update(alias.name for alias in node.names)

        contracts[module_name] = imported_names

    return contracts



def test_service_re_exports_runtime_import_contracts():
    _clear_service_modules()
    _install_aiohttp_stub()

    service = importlib.import_module("service")

    missing = sorted(name for name in RUNTIME_EXPORTS if not hasattr(service, name))
    assert missing == []



def test_runtime_modules_from_service_contracts_are_reexported():
    _clear_service_modules()
    _install_aiohttp_stub()

    service = importlib.import_module("service")

    for module_name, imported_names in _runtime_from_service_contracts().items():
        missing = sorted(name for name in imported_names if not hasattr(service, name))
        assert missing == [], f"{module_name} expects missing service exports: {missing}"



def test_importing_service_does_not_eagerly_load_service_submodules():
    _clear_service_modules()
    _install_aiohttp_stub()

    importlib.import_module("service")

    assert "service.auth_routes" not in sys.modules
    assert "service.http_server" not in sys.modules
    assert "service.session_manager_service" not in sys.modules
    assert "service.ws_server" not in sys.modules



def test_importing_service_defers_runtime_submodule_loading_until_export_access():
    _clear_service_modules()
    _install_aiohttp_stub()

    service = importlib.import_module("service")

    assert service.WsServer is not None
    assert "service.ws_server" in sys.modules
    assert "service.session_manager_service" not in sys.modules



def test_importing_service_defers_auth_http_submodules_until_export_access():
    _clear_service_modules()
    _install_aiohttp_stub()

    service = importlib.import_module("service")

    assert service.create_http_auth_server is not None
    assert "service.http_server" in sys.modules
    assert "service.auth_routes" not in sys.modules

    assert service.AuthRoutes is not None
    assert "service.auth_routes" in sys.modules



def test_session_data_service_submodule_import_is_isolated_from_package_reexport_loading():
    _clear_service_modules()
    _install_aiohttp_stub()

    module = importlib.import_module("service.session_data_service")

    assert hasattr(module, "SessionDataService")
    assert "service.auth_routes" not in sys.modules
    assert "service.http_server" not in sys.modules



def test_queue_state_service_submodule_import_is_isolated_from_package_reexport_loading():
    _clear_service_modules()
    _install_aiohttp_stub()

    module = importlib.import_module("service.queue_state_service")

    assert hasattr(module, "QueueStateService")
    assert "service.auth_routes" not in sys.modules
    assert "service.http_server" not in sys.modules



def test_queue_state_service_submodule_import_does_not_pull_in_unrelated_service_modules():
    _clear_service_modules()
    _install_aiohttp_stub()

    importlib.import_module("service.queue_state_service")

    assert "service.session_manager_service" not in sys.modules
    assert "service.session_data_service" not in sys.modules
    assert "service.user_auth" not in sys.modules



def test_headless_import_contract_resolves_from_service_without_eager_loading_everything():
    _clear_service_modules()
    _install_aiohttp_stub()

    service = importlib.import_module("service")
    imported_names = _runtime_from_service_contracts()["headless"]

    for name in imported_names:
        assert getattr(service, name) is not None

    assert "service.ws_server" in sys.modules
    assert "service.http_server" in sys.modules
    assert "service.auth_routes" not in sys.modules



def test_plugin_runtime_contracts_no_longer_depend_on_service_locator_exports():
    _clear_service_modules()
    _install_aiohttp_stub()

    service = importlib.import_module("service")

    assert not hasattr(service, "get_session_manager_service")
    assert not hasattr(service, "set_session_manager_service")

    loaded = set(name for name in sys.modules if name.startswith("service."))
    assert loaded == set()
