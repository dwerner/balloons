from unittest.mock import MagicMock

from core.manager import SessionManager


def test_session_manager_can_attach_and_return_live_service():
    manager = SessionManager()
    service = MagicMock()

    manager.set_service(service)

    assert manager.get_service() is service
