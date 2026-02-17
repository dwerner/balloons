"""Tests for the WebSocket server with service dispatch."""

import asyncio
import json
import pytest
from dataclasses import dataclass
from typing import Callable
from unittest.mock import AsyncMock, MagicMock

from codegen.ws_expose import (
    ws_expose,
    ws_event,
    ws_service,
    ws_type,
    WsExposeRegistry,
)
from service.ws_server import (
    WsServer,
    ServiceRegistration,
    ConnectedClient,
    MethodNotFoundError,
    InvalidParamsError,
    PARSE_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    INTERNAL_ERROR,
)


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the registry before each test."""
    WsExposeRegistry.clear()
    yield
    WsExposeRegistry.clear()


# --- Test Service Definitions ---
# Note: Classes named with underscore prefix to avoid pytest collection warnings


@ws_type
@dataclass
class ItemFixture:
    """Test item dataclass (not named 'Test*' to avoid pytest collection)."""

    id: str
    name: str
    value: int


@ws_service
class ExampleService:
    """A test service for unit tests."""

    def __init__(self):
        self._items = {}
        self._event_handlers: list[Callable[[str, dict], None]] = []

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit(self, event_name: str, data: dict) -> None:
        for handler in self._event_handlers:
            handler(event_name, data)

    @ws_expose
    async def get_item(self, item_id: str) -> ItemFixture | None:
        """Get an item by ID."""
        return self._items.get(item_id)

    @ws_expose
    async def create_item(self, name: str, value: int = 0) -> ItemFixture:
        """Create a new item."""
        import uuid

        item_id = str(uuid.uuid4())[:8]
        item = ItemFixture(id=item_id, name=name, value=value)
        self._items[item_id] = item
        self._emit("itemCreated", {"item": item})
        return item

    @ws_expose
    async def list_items(self) -> list[ItemFixture]:
        """List all items."""
        return list(self._items.values())

    @ws_expose
    async def echo(self, message: str) -> str:
        """Echo a message back."""
        return message

    @ws_expose
    def sync_method(self) -> str:
        """A synchronous method."""
        return "sync result"

    @ws_event
    async def on_item_created(self) -> ItemFixture:
        """Emitted when an item is created."""
        ...

    @ws_event
    async def on_item_updated(self) -> ItemFixture:
        """Emitted when an item is updated."""
        ...


@ws_service
class AnotherService:
    """Another service for testing conflicts."""

    def __init__(self):
        self._event_handlers: list[Callable[[str, dict], None]] = []

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        self._event_handlers.append(handler)

    @ws_expose
    async def echo(self, message: str) -> str:
        """Echo with prefix."""
        return f"another: {message}"

    @ws_expose
    async def unique_method(self) -> str:
        """A method unique to this service."""
        return "unique"


# --- Test Cases ---


class ExampleServiceRegistration:
    def test_register_service(self):
        server = WsServer()
        service = ExampleService()

        server.register_service(service)

        assert "ExampleService" in server.get_registered_services()
        methods = server.get_registered_methods()
        assert "getItem" in methods
        assert "createItem" in methods
        assert "listItems" in methods
        assert "echo" in methods

    def test_register_undecorated_service_raises(self):
        server = WsServer()

        class NotAService:
            pass

        with pytest.raises(ValueError, match="must be decorated with @ws_service"):
            server.register_service(NotAService())

    def test_method_collision_logs_warning(self, caplog):
        server = WsServer()
        service1 = ExampleService()
        service2 = AnotherService()

        server.register_service(service1)
        server.register_service(service2)

        # Should log warning about collision
        assert "collision" in caplog.text.lower() or "echo" in caplog.text

    def test_qualified_method_names(self):
        server = WsServer()
        service1 = ExampleService()
        service2 = AnotherService()

        server.register_service(service1)
        server.register_service(service2)

        # Both qualified names should work
        assert "ExampleService.echo" in server._qualified_dispatch
        assert "AnotherService.echo" in server._qualified_dispatch


class TestMethodDispatch:
    @pytest.fixture
    def server(self):
        server = WsServer()
        server.register_service(ExampleService())
        return server

    @pytest.fixture
    def mock_client(self):
        """Create a mock ConnectedClient for testing dispatch."""
        mock_ws = MagicMock()
        return ConnectedClient(websocket=mock_ws, client_id="test-client-123")

    @pytest.mark.asyncio
    async def test_dispatch_simple_method(self, server, mock_client):
        result = await server._dispatch_method("echo", {"message": "hello"}, mock_client)
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_dispatch_with_camel_case_params(self, server, mock_client):
        # Wire format uses camelCase, should convert to snake_case
        result = await server._dispatch_method(
            "createItem", {"name": "test", "value": 42}, mock_client
        )
        assert result["name"] == "test"
        assert result["value"] == 42

    @pytest.mark.asyncio
    async def test_dispatch_with_default_params(self, server, mock_client):
        # value has default of 0
        result = await server._dispatch_method("createItem", {"name": "test"}, mock_client)
        assert result["value"] == 0

    @pytest.mark.asyncio
    async def test_dispatch_method_not_found(self, server, mock_client):
        with pytest.raises(MethodNotFoundError) as exc_info:
            await server._dispatch_method("nonExistent", {}, mock_client)

        assert "nonExistent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dispatch_missing_required_param(self, server, mock_client):
        with pytest.raises(InvalidParamsError) as exc_info:
            await server._dispatch_method("echo", {}, mock_client)

        assert "message" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dispatch_qualified_method(self, server, mock_client):
        result = await server._dispatch_method("ExampleService.echo", {"message": "qualified"}, mock_client)
        assert result == "qualified"

    @pytest.mark.asyncio
    async def test_dispatch_returns_none(self, server, mock_client):
        result = await server._dispatch_method("getItem", {"itemId": "nonexistent"}, mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_dispatch_sync_method(self, server, mock_client):
        result = await server._dispatch_method("syncMethod", {}, mock_client)
        assert result == "sync result"


class TestResultSerialization:
    @pytest.fixture
    def server(self):
        server = WsServer()
        server.register_service(ExampleService())
        return server

    def test_serialize_dataclass(self, server):
        item = ItemFixture(id="123", name="test", value=42)
        result = server._serialize_result(item)

        assert result == {"id": "123", "name": "test", "value": 42}

    def test_serialize_list_of_dataclasses(self, server):
        items = [
            ItemFixture(id="1", name="a", value=1),
            ItemFixture(id="2", name="b", value=2),
        ]
        result = server._serialize_result(items)

        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["name"] == "b"

    def test_serialize_dict_with_camel_case(self, server):
        data = {"snake_case_key": "value", "another_key": 123}
        result = server._serialize_result(data)

        assert result == {"snakeCaseKey": "value", "anotherKey": 123}

    def test_serialize_tuple_to_list(self, server):
        result = server._serialize_result((1, 2, 3))
        assert result == [1, 2, 3]

    def test_serialize_none(self, server):
        assert server._serialize_result(None) is None

    def test_serialize_primitives(self, server):
        assert server._serialize_result("string") == "string"
        assert server._serialize_result(42) == 42
        assert server._serialize_result(3.14) == 3.14
        assert server._serialize_result(True) is True


class TestMessageHandling:
    @pytest.fixture
    def server(self):
        server = WsServer()
        server.register_service(ExampleService())
        return server

    @pytest.fixture
    def mock_client(self):
        from service.ws_server import ConnectedClient

        websocket = MagicMock()
        return ConnectedClient(websocket=websocket)

    @pytest.mark.asyncio
    async def test_handle_valid_request(self, server, mock_client):
        message = json.dumps({"id": "req-1", "method": "echo", "params": {"message": "test"}})

        response = await server._handle_message(message, mock_client)

        assert response["id"] == "req-1"
        assert response["result"] == "test"

    @pytest.mark.asyncio
    async def test_handle_parse_error(self, server, mock_client):
        response = await server._handle_message("not json", mock_client)

        assert response["id"] is None
        assert response["error"]["code"] == PARSE_ERROR

    @pytest.mark.asyncio
    async def test_handle_missing_method(self, server, mock_client):
        message = json.dumps({"id": "req-1", "params": {}})

        response = await server._handle_message(message, mock_client)

        assert response["id"] == "req-1"
        assert response["error"]["code"] == INVALID_REQUEST
        assert "method" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_handle_invalid_method_type(self, server, mock_client):
        message = json.dumps({"id": "req-1", "method": 123})

        response = await server._handle_message(message, mock_client)

        assert response["error"]["code"] == INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_handle_invalid_params_type(self, server, mock_client):
        message = json.dumps({"id": "req-1", "method": "echo", "params": "invalid"})

        response = await server._handle_message(message, mock_client)

        assert response["error"]["code"] == INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_handle_method_not_found(self, server, mock_client):
        message = json.dumps({"id": "req-1", "method": "nonExistent", "params": {}})

        response = await server._handle_message(message, mock_client)

        assert response["id"] == "req-1"
        assert response["error"]["code"] == METHOD_NOT_FOUND

    @pytest.mark.asyncio
    async def test_handle_invalid_params(self, server, mock_client):
        message = json.dumps({"id": "req-1", "method": "echo", "params": {}})

        response = await server._handle_message(message, mock_client)

        assert response["id"] == "req-1"
        assert response["error"]["code"] == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_handle_request_without_params(self, server, mock_client):
        message = json.dumps({"id": "req-1", "method": "listItems"})

        response = await server._handle_message(message, mock_client)

        assert response["id"] == "req-1"
        assert "result" in response
        assert isinstance(response["result"], list)

    @pytest.mark.asyncio
    async def test_handle_request_with_null_params(self, server, mock_client):
        message = json.dumps({"id": "req-1", "method": "listItems", "params": None})

        response = await server._handle_message(message, mock_client)

        assert "result" in response


class TestResponseBuilding:
    @pytest.fixture
    def server(self):
        return WsServer()

    def test_success_response(self, server):
        response = server._success_response("req-123", {"data": "value"})

        assert response == {"id": "req-123", "result": {"data": "value"}}

    def test_error_response(self, server):
        response = server._error_response("req-123", METHOD_NOT_FOUND, "Not found")

        assert response == {
            "id": "req-123",
            "error": {"code": METHOD_NOT_FOUND, "message": "Not found"},
        }

    def test_error_response_with_null_id(self, server):
        response = server._error_response(None, PARSE_ERROR, "Parse error")

        assert response["id"] is None


class TestEventBroadcasting:
    @pytest.fixture
    def server(self):
        server = WsServer()
        server.register_service(ExampleService())
        return server

    @pytest.mark.asyncio
    async def test_service_event_triggers_broadcast(self, server):
        # Track broadcast calls
        broadcast_messages = []

        async def mock_broadcast(message, target_clients=None):
            broadcast_messages.append(message)

        server._broadcast = mock_broadcast

        # Trigger an event by calling createItem
        service = server._services["ExampleService"].instance
        await service.create_item("test", 10)

        # Give the event loop a chance to run the scheduled task
        await asyncio.sleep(0)

        # Should have broadcast itemCreated event
        assert len(broadcast_messages) == 1
        assert broadcast_messages[0]["event"] == "itemCreated"

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_clients(self, server):
        # Create mock websockets
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        # Need to add client info for the broadcast to work
        client1 = ConnectedClient(websocket=mock_ws1, client_id="client-1")
        client2 = ConnectedClient(websocket=mock_ws2, client_id="client-2")

        server._clients.add(mock_ws1)
        server._clients.add(mock_ws2)
        server._client_info[mock_ws1] = client1
        server._client_info[mock_ws2] = client2

        await server._broadcast({"event": "testEvent", "data": {}})

        mock_ws1.send.assert_called_once()
        mock_ws2.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_to_no_clients(self, server):
        # Should not raise when no clients
        await server._broadcast({"event": "testEvent", "data": {}})

    @pytest.mark.asyncio
    async def test_broadcast_to_targeted_clients(self, server):
        """Test that targeted broadcast only sends to specified clients."""
        # Create mock websockets
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()
        mock_ws3 = AsyncMock()

        # Set up client info
        client1 = ConnectedClient(websocket=mock_ws1, client_id="client-1")
        client2 = ConnectedClient(websocket=mock_ws2, client_id="client-2")
        client3 = ConnectedClient(websocket=mock_ws3, client_id="client-3")

        server._clients.add(mock_ws1)
        server._clients.add(mock_ws2)
        server._clients.add(mock_ws3)
        server._client_info[mock_ws1] = client1
        server._client_info[mock_ws2] = client2
        server._client_info[mock_ws3] = client3

        # Broadcast to only clients 1 and 3
        await server._broadcast(
            {"event": "testEvent", "data": {}},
            target_clients={"client-1", "client-3"}
        )

        mock_ws1.send.assert_called_once()
        mock_ws2.send.assert_not_called()
        mock_ws3.send.assert_called_once()


class TestClientManagement:
    def test_client_count(self):
        server = WsServer()

        assert server.client_count == 0

        mock_ws = MagicMock()
        server._clients.add(mock_ws)

        assert server.client_count == 1


class TestServerLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        server = WsServer(host="127.0.0.1", port=0)  # Port 0 = random available port
        server.register_service(ExampleService())

        await server.start()
        assert server._running is True
        assert server._server is not None

        await server.stop()
        assert server._running is False
        assert server._server is None

    @pytest.mark.asyncio
    async def test_double_start_warning(self, caplog):
        server = WsServer(host="127.0.0.1", port=0)
        server.register_service(ExampleService())

        await server.start()
        await server.start()  # Should warn

        assert "already running" in caplog.text.lower()

        await server.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        server = WsServer()
        # Should not raise
        await server.stop()


class TestCreateServerHelper:
    @pytest.mark.asyncio
    async def test_create_server(self):
        from service.ws_server import create_server

        service = ExampleService()
        server = await create_server([service], host="127.0.0.1", port=0)

        assert server._running is True
        assert "ExampleService" in server.get_registered_services()

        await server.stop()


class TestIntegration:
    """Integration tests that verify full request/response flow."""

    @pytest.fixture
    def server(self):
        server = WsServer()
        server.register_service(ExampleService())
        return server

    @pytest.fixture
    def mock_client(self):
        from service.ws_server import ConnectedClient

        websocket = MagicMock()
        return ConnectedClient(websocket=websocket)

    @pytest.mark.asyncio
    async def test_full_crud_flow(self, server, mock_client):
        # Create
        create_msg = json.dumps({
            "id": "1",
            "method": "createItem",
            "params": {"name": "Widget", "value": 100}
        })
        response = await server._handle_message(create_msg, mock_client)
        assert response["result"]["name"] == "Widget"
        item_id = response["result"]["id"]

        # Read
        get_msg = json.dumps({
            "id": "2",
            "method": "getItem",
            "params": {"itemId": item_id}
        })
        response = await server._handle_message(get_msg, mock_client)
        assert response["result"]["name"] == "Widget"

        # List
        list_msg = json.dumps({"id": "3", "method": "listItems"})
        response = await server._handle_message(list_msg, mock_client)
        assert len(response["result"]) == 1

    @pytest.mark.asyncio
    async def test_multiple_services(self, mock_client):
        server = WsServer()
        server.register_service(ExampleService())
        server.register_service(AnotherService())

        # Call unique method on AnotherService
        msg = json.dumps({"id": "1", "method": "uniqueMethod"})
        response = await server._handle_message(msg, mock_client)
        assert response["result"] == "unique"

        # Call qualified echo on ExampleService
        msg = json.dumps({
            "id": "2",
            "method": "ExampleService.echo",
            "params": {"message": "test"}
        })
        response = await server._handle_message(msg, mock_client)
        assert response["result"] == "test"

        # Call qualified echo on AnotherService
        msg = json.dumps({
            "id": "3",
            "method": "AnotherService.echo",
            "params": {"message": "test"}
        })
        response = await server._handle_message(msg, mock_client)
        assert response["result"] == "another: test"


class TestWebSocketConfig:
    """Tests for WebSocket configuration support."""

    def test_server_with_config(self):
        from config import WebSocketConfig, TLSConfig

        config = WebSocketConfig(
            host="0.0.0.0",
            port=9000,
            tls=TLSConfig(enabled=False),
        )
        server = WsServer(config=config)

        assert server.host == "0.0.0.0"
        assert server.port == 9000
        assert server.tls_enabled is False
        assert server.url == "ws://0.0.0.0:9000"

    def test_server_config_overrides_args(self):
        from config import WebSocketConfig

        config = WebSocketConfig(host="192.168.1.1", port=8080)
        # Config should override host/port args
        server = WsServer(host="localhost", port=8765, config=config)

        assert server.host == "192.168.1.1"
        assert server.port == 8080

    def test_server_url_property_ws(self):
        server = WsServer(host="example.com", port=443)
        assert server.url == "ws://example.com:443"

    def test_server_url_property_wss(self):
        from config import WebSocketConfig, TLSConfig

        config = WebSocketConfig(
            host="secure.example.com",
            port=443,
            tls=TLSConfig(enabled=True, cert_path="/tmp/cert.pem", key_path="/tmp/key.pem"),
        )
        server = WsServer(config=config)
        assert server.url == "wss://secure.example.com:443"


class TestTLSConfig:
    """Tests for TLS configuration."""

    def test_tls_config_defaults(self):
        from config import TLSConfig

        config = TLSConfig()
        assert config.enabled is False
        assert config.cert_path is None
        assert config.key_path is None

    def test_tls_config_path_expansion(self):
        from config import TLSConfig
        import os

        config = TLSConfig(
            enabled=True,
            cert_path="~/.balloons/certs/dev.crt",
            key_path="~/.balloons/certs/dev.key",
        )

        cert_path = config.get_cert_path()
        key_path = config.get_key_path()

        assert cert_path is not None
        assert key_path is not None
        assert str(cert_path).startswith(os.path.expanduser("~"))
        assert str(key_path).startswith(os.path.expanduser("~"))

    def test_tls_config_validate_disabled(self):
        from config import TLSConfig

        config = TLSConfig(enabled=False)
        # Should not raise
        config.validate()

    def test_tls_config_validate_missing_cert(self):
        from config import TLSConfig

        config = TLSConfig(enabled=True, key_path="/tmp/key.pem")
        with pytest.raises(ValueError, match="cert_path not configured"):
            config.validate()

    def test_tls_config_validate_missing_key(self):
        from config import TLSConfig

        config = TLSConfig(enabled=True, cert_path="/tmp/cert.pem")
        with pytest.raises(ValueError, match="key_path not configured"):
            config.validate()

    def test_tls_config_validate_file_not_found(self, tmp_path):
        from config import TLSConfig

        config = TLSConfig(
            enabled=True,
            cert_path=str(tmp_path / "nonexistent.crt"),
            key_path=str(tmp_path / "nonexistent.key"),
        )
        with pytest.raises(ValueError, match="Certificate file not found"):
            config.validate()


class TestWebSocketConfigParsing:
    """Tests for parsing WebSocket config from YAML."""

    def test_parse_websocket_config(self, tmp_path):
        from config import Config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
backends:
  claude: {}

websocket:
  enabled: true
  host: 0.0.0.0
  port: 9000
  tls:
    enabled: false
""")

        config = Config._load_from_file(config_file)
        assert config.websocket.enabled is True
        assert config.websocket.host == "0.0.0.0"
        assert config.websocket.port == 9000
        assert config.websocket.tls.enabled is False

    def test_parse_websocket_config_with_tls(self, tmp_path):
        from config import Config

        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_text("CERT")
        key_file.write_text("KEY")

        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"""
backends:
  claude: {{}}

websocket:
  host: localhost
  port: 8765
  tls:
    enabled: true
    cert_path: {cert_file}
    key_path: {key_file}
""")

        config = Config._load_from_file(config_file)
        assert config.websocket.tls.enabled is True
        assert config.websocket.tls.cert_path == str(cert_file)
        assert config.websocket.tls.key_path == str(key_file)

    def test_parse_websocket_config_defaults(self, tmp_path):
        from config import Config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
backends:
  claude: {}
""")

        config = Config._load_from_file(config_file)
        assert config.websocket.enabled is False  # Default disabled
        assert config.websocket.host == "localhost"
        assert config.websocket.port == 8765
        assert config.websocket.tls.enabled is False

    def test_parse_websocket_config_enabled(self, tmp_path):
        from config import Config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
backends:
  claude: {}

websocket:
  enabled: true
  host: 0.0.0.0
  port: 9000
""")

        config = Config._load_from_file(config_file)
        assert config.websocket.enabled is True
        assert config.websocket.host == "0.0.0.0"
        assert config.websocket.port == 9000

    def test_websocket_config_get_url(self):
        from config import WebSocketConfig, TLSConfig

        ws_config = WebSocketConfig(host="localhost", port=8765)
        assert ws_config.get_url() == "ws://localhost:8765"

        wss_config = WebSocketConfig(
            host="localhost",
            port=443,
            tls=TLSConfig(enabled=True),
        )
        assert wss_config.get_url() == "wss://localhost:443"


class TestTLSServer:
    """Tests for TLS-enabled server."""

    @pytest.mark.asyncio
    async def test_start_with_missing_cert_raises(self):
        from config import WebSocketConfig, TLSConfig

        config = WebSocketConfig(
            host="localhost",
            port=0,
            tls=TLSConfig(
                enabled=True,
                cert_path="/nonexistent/cert.pem",
                key_path="/nonexistent/key.pem",
            ),
        )
        server = WsServer(config=config)

        with pytest.raises(ValueError, match="Certificate file not found"):
            await server.start()

    @pytest.mark.asyncio
    async def test_start_with_valid_certs(self, tmp_path):
        """Test that server can start with valid certificates."""
        # Generate a simple self-signed cert for testing
        try:
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID
            import datetime
        except ImportError:
            pytest.skip("cryptography package not installed")

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Generate certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ])

        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(private_key, hashes.SHA256())
        )

        # Write cert and key
        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        with open(key_path, "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        # Create server with TLS config
        from config import WebSocketConfig, TLSConfig

        config = WebSocketConfig(
            host="127.0.0.1",
            port=0,  # Random port
            tls=TLSConfig(
                enabled=True,
                cert_path=str(cert_path),
                key_path=str(key_path),
            ),
        )

        server = WsServer(config=config)
        server.register_service(ExampleService())

        await server.start()
        assert server._running is True
        assert server._ssl_context is not None
        assert server.tls_enabled is True

        await server.stop()


class TestJWTConfig:
    """Tests for JWT configuration in WebSocket config."""

    def test_jwt_config_defaults(self):
        from config import JWTConfig

        config = JWTConfig()
        assert config.enabled is True
        assert config.secret is None
        assert config.expiration_seconds == 86400

    def test_parse_jwt_config_from_yaml(self, tmp_path):
        from config import Config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
backends:
  claude: {}

websocket:
  host: localhost
  port: 8765
  jwt:
    enabled: true
    secret: my-secret-key
    expiration_seconds: 3600
""")

        config = Config._load_from_file(config_file)
        assert config.websocket.jwt.enabled is True
        assert config.websocket.jwt.secret == "my-secret-key"
        assert config.websocket.jwt.expiration_seconds == 3600

    def test_parse_jwt_config_disabled(self, tmp_path):
        from config import Config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
backends:
  claude: {}

websocket:
  jwt:
    enabled: false
""")

        config = Config._load_from_file(config_file)
        assert config.websocket.jwt.enabled is False

    def test_jwt_config_defaults_when_not_specified(self, tmp_path):
        from config import Config

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
backends:
  claude: {}
""")

        config = Config._load_from_file(config_file)
        assert config.websocket.jwt.enabled is True  # Default
        assert config.websocket.jwt.secret is None


class TestJWTAuthentication:
    """Tests for JWT authentication in WsServer."""

    def test_jwt_enabled_property_true(self):
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=True, secret="test-secret"),
        )
        server = WsServer(config=config)
        assert server.jwt_enabled is True

    def test_jwt_enabled_property_false(self):
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=False),
        )
        server = WsServer(config=config)
        assert server.jwt_enabled is False

    def test_jwt_enabled_property_no_config(self):
        server = WsServer()
        assert server.jwt_enabled is False

    def test_generate_token_returns_token(self):
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=True, secret="test-secret-key-32-chars-long!!"),
        )
        server = WsServer(config=config)

        token = server.generate_token("my-session")
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_generate_token_returns_none_when_disabled(self):
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=False),
        )
        server = WsServer(config=config)

        token = server.generate_token("my-session")
        assert token is None

    def test_generate_token_returns_none_when_no_config(self):
        server = WsServer()
        token = server.generate_token("my-session")
        assert token is None

    @pytest.mark.asyncio
    async def test_authenticate_connection_disabled(self):
        """When JWT is disabled, all connections are authenticated."""
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=False),
        )
        server = WsServer(config=config)

        # Mock websocket
        mock_ws = MagicMock()
        mock_ws.request = None

        authenticated, subject, error = await server._authenticate_connection(mock_ws)
        assert authenticated is True
        assert subject is None
        assert error is None

    @pytest.mark.asyncio
    async def test_authenticate_connection_no_token(self):
        """When JWT is enabled but no token provided, reject connection."""
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=True, secret="test-secret"),
        )
        server = WsServer(config=config)

        # Mock websocket without token
        mock_ws = MagicMock()
        mock_ws.request = MagicMock()
        mock_ws.request.path = "/"
        mock_ws.subprotocol = None

        authenticated, subject, error = await server._authenticate_connection(mock_ws)
        assert authenticated is False
        assert subject is None
        assert "token required" in error.lower()

    @pytest.mark.asyncio
    async def test_authenticate_connection_with_query_token(self):
        """Token in query parameter is validated."""
        from config import WebSocketConfig, JWTConfig

        secret = "test-secret-key-32-characters-!!"
        config = WebSocketConfig(
            jwt=JWTConfig(enabled=True, secret=secret),
        )
        server = WsServer(config=config)

        # Generate a valid token
        token = server.generate_token("session-123")

        # Mock websocket with token in query
        mock_ws = MagicMock()
        mock_ws.request = MagicMock()
        mock_ws.request.path = f"/?token={token}"
        mock_ws.subprotocol = None
        mock_ws.request.headers = {}

        authenticated, subject, error = await server._authenticate_connection(mock_ws)
        assert authenticated is True
        assert subject == "session-123"
        assert error is None

    @pytest.mark.asyncio
    async def test_authenticate_connection_invalid_token(self):
        """Invalid token is rejected."""
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=True, secret="test-secret"),
        )
        server = WsServer(config=config)

        # Mock websocket with invalid token
        mock_ws = MagicMock()
        mock_ws.request = MagicMock()
        mock_ws.request.path = "/?token=invalid-token"
        mock_ws.subprotocol = None

        authenticated, subject, error = await server._authenticate_connection(mock_ws)
        assert authenticated is False
        assert subject is None
        assert error is not None

    def test_extract_token_from_query(self):
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=True, secret="test"),
        )
        server = WsServer(config=config)

        # Mock websocket with token in query
        mock_ws = MagicMock()
        mock_ws.request = MagicMock()
        mock_ws.request.path = "/?token=mytoken123&other=value"

        token = server._extract_token_from_request(mock_ws)
        assert token == "mytoken123"

    def test_extract_token_from_request_no_token(self):
        from config import WebSocketConfig, JWTConfig

        config = WebSocketConfig(
            jwt=JWTConfig(enabled=True, secret="test"),
        )
        server = WsServer(config=config)

        # Mock websocket without token
        mock_ws = MagicMock()
        mock_ws.request = MagicMock()
        mock_ws.request.path = "/"
        mock_ws.subprotocol = None
        mock_ws.request.headers = {}

        token = server._extract_token_from_request(mock_ws)
        assert token is None


class TestConnectedClientWithAuth:
    """Tests for ConnectedClient with authentication fields."""

    def test_connected_client_default_not_authenticated(self):
        mock_ws = MagicMock()
        client = ConnectedClient(websocket=mock_ws)

        assert client.authenticated is False
        assert client.token_subject is None

    def test_connected_client_with_authentication(self):
        mock_ws = MagicMock()
        client = ConnectedClient(
            websocket=mock_ws,
            authenticated=True,
            token_subject="user-123",
        )

        assert client.authenticated is True
        assert client.token_subject == "user-123"


class TestWebSocketConfigEnabled:
    """Tests for WebSocketConfig.enabled field."""

    def test_websocket_config_enabled_default(self):
        """Default value should be False."""
        from config import WebSocketConfig

        config = WebSocketConfig()
        assert config.enabled is False

    def test_websocket_config_enabled_true(self):
        """Can enable WebSocket server."""
        from config import WebSocketConfig

        config = WebSocketConfig(enabled=True)
        assert config.enabled is True

    def test_websocket_config_enabled_with_all_options(self):
        """Enabled works with all other options."""
        from config import WebSocketConfig, TLSConfig, JWTConfig

        config = WebSocketConfig(
            enabled=True,
            host="0.0.0.0",
            port=9000,
            tls=TLSConfig(enabled=False),
            jwt=JWTConfig(enabled=False),
        )
        assert config.enabled is True
        assert config.host == "0.0.0.0"
        assert config.port == 9000
