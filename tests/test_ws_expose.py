"""Tests for the ws_expose decorator system."""

import pytest
from dataclasses import dataclass
from typing import Optional

from codegen.ws_expose import (
    ws_expose,
    ws_event,
    ws_type,
    ws_service,
    WsExposeRegistry,
    to_camel_case,
    to_snake_case,
    python_to_ts_type,
    generate_ts_interface,
)


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the registry before each test."""
    WsExposeRegistry.clear()
    yield
    WsExposeRegistry.clear()


class TestCaseConversion:
    def test_to_camel_case(self):
        assert to_camel_case("hello_world") == "helloWorld"
        assert to_camel_case("get_session_id") == "getSessionId"
        assert to_camel_case("simple") == "simple"
        assert to_camel_case("already_Camel") == "alreadyCamel"

    def test_to_snake_case(self):
        assert to_snake_case("helloWorld") == "hello_world"
        assert to_snake_case("getSessionId") == "get_session_id"
        assert to_snake_case("simple") == "simple"


class TestTypeConversion:
    def test_basic_types(self):
        assert python_to_ts_type(str) == "string"
        assert python_to_ts_type(int) == "number"
        assert python_to_ts_type(float) == "number"
        assert python_to_ts_type(bool) == "boolean"

    def test_optional_type(self):
        assert python_to_ts_type(str | None) == "string | null"
        assert python_to_ts_type(Optional[int]) == "number | null"

    def test_list_type(self):
        assert python_to_ts_type(list[str]) == "string[]"
        assert python_to_ts_type(list[int]) == "number[]"

    def test_dict_type(self):
        assert python_to_ts_type(dict[str, int]) == "Record<string, number>"
        assert python_to_ts_type(dict[str, list[str]]) == "Record<string, string[]>"

    def test_tuple_type(self):
        assert python_to_ts_type(tuple[int, str]) == "[number, string]"
        assert python_to_ts_type(tuple[int, int, int]) == "[number, number, number]"


class TestWsType:
    def test_registers_dataclass(self):
        @ws_type
        @dataclass
        class TestData:
            id: str
            count: int

        types = WsExposeRegistry.get_types()
        assert TestData in types

    def test_generates_typescript_interface(self):
        @ws_type
        @dataclass
        class UserInfo:
            user_id: str
            display_name: str
            is_active: bool
            email: Optional[str] = None

        ts = generate_ts_interface(UserInfo)
        assert "export interface UserInfo" in ts
        assert "userId: string" in ts
        assert "displayName: string" in ts
        assert "isActive: boolean" in ts
        assert "email?: string | null" in ts

    def test_rejects_non_dataclass(self):
        with pytest.raises(TypeError):

            @ws_type
            class NotADataclass:
                pass


class TestWsExpose:
    def test_decorates_method(self):
        @ws_service
        class TestService:
            @ws_expose
            async def get_data(self, item_id: str) -> dict:
                return {}

        services = WsExposeRegistry.get_services()
        assert "TestService" in services
        service = services["TestService"]
        assert len(service.methods) == 1
        method = service.methods[0]
        assert method.name == "get_data"
        assert method.wire_name == "getData"

    def test_custom_wire_name(self):
        @ws_service
        class TestService:
            @ws_expose(name="fetchItem")
            async def get_item(self, item_id: str) -> dict:
                return {}

        service = WsExposeRegistry.get_services()["TestService"]
        assert service.methods[0].wire_name == "fetchItem"

    def test_extracts_parameters(self):
        @ws_service
        class TestService:
            @ws_expose
            async def search(
                self, query: str, limit: int = 10, offset: int = 0
            ) -> list[dict]:
                return []

        service = WsExposeRegistry.get_services()["TestService"]
        method = service.methods[0]

        assert len(method.params) == 3
        assert method.params[0].name == "query"
        assert method.params[0].required is True
        assert method.params[1].name == "limit"
        assert method.params[1].required is False
        assert method.params[1].default == 10


class TestWsEvent:
    def test_decorates_event(self):
        @ws_service
        class TestService:
            @ws_event
            async def on_data_changed(self) -> dict:
                pass

        service = WsExposeRegistry.get_services()["TestService"]
        assert len(service.events) == 1
        event = service.events[0]
        assert event.name == "on_data_changed"
        assert event.wire_name == "onDataChanged"

    def test_event_with_pattern(self):
        @ws_service
        class TestService:
            @ws_event("items.*")
            async def on_item_event(self) -> dict:
                pass

        service = WsExposeRegistry.get_services()["TestService"]
        event = service.events[0]
        assert event.pattern == "items.*"


class TestWsService:
    def test_registers_service(self):
        @ws_service
        class MyService:
            """A test service."""

            @ws_expose
            async def method_a(self) -> str:
                return ""

            @ws_expose
            async def method_b(self, x: int) -> int:
                return x

        services = WsExposeRegistry.get_services()
        assert "MyService" in services
        service = services["MyService"]
        assert service.docstring == "A test service."
        assert len(service.methods) == 2

    def test_custom_service_name(self):
        @ws_service(name="CustomName")
        class MyService:
            pass

        services = WsExposeRegistry.get_services()
        service = services["MyService"]
        assert service.wire_name == "CustomName"


class TestFullIntegration:
    def test_complete_service(self):
        @ws_type
        @dataclass
        class Item:
            id: str
            name: str
            count: int

        @ws_service
        class ItemService:
            """Manages items."""

            @ws_expose
            async def get_item(self, item_id: str) -> Item | None:
                pass

            @ws_expose
            async def list_items(self) -> list[Item]:
                pass

            @ws_expose
            async def create_item(self, name: str, count: int = 0) -> Item:
                pass

            @ws_event
            async def on_item_created(self) -> Item:
                pass

            @ws_event
            async def on_item_updated(self) -> Item:
                pass

        # Verify types
        types = WsExposeRegistry.get_types()
        assert Item in types

        # Verify service
        services = WsExposeRegistry.get_services()
        service = services["ItemService"]
        assert len(service.methods) == 3
        assert len(service.events) == 2

        # Verify TypeScript generation
        ts = generate_ts_interface(Item)
        assert "export interface Item" in ts
        assert "id: string" in ts
        assert "count: number" in ts
