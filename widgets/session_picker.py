from textual.screen import ModalScreen
from textual.widgets import Static, Button, ListView, ListItem, Label
from textual.containers import Vertical, Horizontal
from textual.message import Message

from session import Session


class SessionItem(ListItem):
    """A session item in the list."""

    def __init__(self, session_id: str, created: str, model: str, title: str = "", **kwargs):
        super().__init__(**kwargs)
        self.session_id = session_id
        self.created = created
        self.model = model
        self.title = title

    def compose(self):
        if self.title:
            yield Label(f"{self.created[:16]}  {self.title[:30]}")
        else:
            yield Label(f"{self.created[:16]}  {self.model or 'unknown'}")


class SessionPicker(ModalScreen[Session | None]):
    """Modal for picking or creating a session."""

    DEFAULT_CSS = """
    SessionPicker {
        align: center middle;
    }

    #dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }

    #session-list {
        height: auto;
        max-height: 15;
        margin: 1 0;
        border: solid $primary;
    }

    #no-sessions {
        padding: 1;
        text-align: center;
        color: $text-muted;
    }

    #buttons {
        margin-top: 1;
        align: center middle;
        height: auto;
    }

    Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("n", "new_session", "New"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sessions: list[tuple[str, str, str, str]] = []

    def compose(self):
        with Vertical(id="dialog"):
            yield Static("Session Manager", id="title")

            self._sessions = Session.list_sessions()

            if self._sessions:
                with ListView(id="session-list"):
                    for session_id, created, model, title in self._sessions:
                        yield SessionItem(session_id, created, model, title)
            else:
                yield Static("No previous sessions", id="no-sessions")

            with Horizontal(id="buttons"):
                yield Button("New Session", id="new-btn", variant="primary")
                if self._sessions:
                    yield Button("Load Selected", id="load-btn", variant="default")
                yield Button("Cancel", id="cancel-btn", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-btn":
            self.dismiss(Session())
        elif event.button.id == "load-btn":
            self._load_selected()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Double-click or Enter on list item loads it."""
        self._load_selected()

    def _load_selected(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        if list_view.highlighted_child:
            item = list_view.highlighted_child
            if isinstance(item, SessionItem):
                session = Session.load(item.session_id)
                if session:
                    self.dismiss(session)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_new_session(self) -> None:
        self.dismiss(Session())
