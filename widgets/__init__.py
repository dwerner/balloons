from .chat_log import ChatLogView, MoreBelowIndicator, NewMessagesIndicator
from .input_box import InputBox
from .stash_popup import StashPopup
from core.stash import MessageStash, StashedMessage
from .message_queue_popup import MessageQueuePopup
from .status_bar import StatusBar
from .context_tree import ContextTreeView
from .nested_tree import NestedTreeView
from .splitter import VerticalSplitter, HorizontalSplitter
from .context_preview import ContextPreview, ConfirmDialog, HelpModal, NewSessionModal, NewSessionResult
from .task_pane import TaskPane
from .tool_bar import ToolBar
from .preferences_modal import PreferencesModal
from core.preferences import ToolPreferences, DEFAULT_TOOLS
from .with_widget import WithWidget
from .with_result_widget import WithResultWidget
from .debug_pane import DebugPane
from .fork_marker import ForkMarker
from .merge_marker import MergeMarker
from .link_marker import LinkMarker
from .breadcrumb import Breadcrumb
from .fork_proposal_modal import ForkProposalModal, ForkProposalResult
from .merge_proposal_modal import MergeProposalModal, MergeProposalResult
from .slides_pane import SlidesPane, SlideCard
from .presentation_screen import PresentationScreen
from .directory_picker import DirectoryBrowser
from .entity_pane import EntityPane

# Backwards compatibility aliases
ContextTree = ContextTreeView
NestedSessionTree = NestedTreeView

__all__ = [
    "ChatLogView",
    "MoreBelowIndicator",
    "NewMessagesIndicator",
    "InputBox",
    "StashPopup",
    "MessageStash",
    "StashedMessage",
    "MessageQueuePopup",
    "StatusBar",
    "ContextTreeView",
    "NestedTreeView",
    # Backwards compatibility
    "ContextTree",
    "NestedSessionTree",
    "VerticalSplitter",
    "HorizontalSplitter",
    "ContextPreview",
    "ConfirmDialog",
    "HelpModal",
    "NewSessionModal",
    "NewSessionResult",
    "TaskPane",
    "ToolBar",
    "PreferencesModal",
    "ToolPreferences",
    "DEFAULT_TOOLS",
    "WithWidget",
    "WithResultWidget",
    "DebugPane",
    "ForkMarker",
    "MergeMarker",
    "LinkMarker",
    "Breadcrumb",
    "ForkProposalModal",
    "ForkProposalResult",
    "MergeProposalModal",
    "MergeProposalResult",
    "SlidesPane",
    "SlideCard",
    "PresentationScreen",
    "DirectoryBrowser",
    "EntityPane",
]
