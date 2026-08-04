//! Prompt types for language model interactions.

use serde::{Deserialize, Serialize};

/// A prompt consisting of messages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Prompt {
    pub messages: Vec<Message>,
}

impl Prompt {
    pub fn new(messages: Vec<Message>) -> Self {
        Self { messages }
    }

    pub fn with_system(system: impl Into<String>) -> Self {
        Self {
            messages: vec![Message::system(system)],
        }
    }

    pub fn with_user(user: impl Into<String>) -> Self {
        Self {
            messages: vec![Message::user(user)],
        }
    }
}

/// A message in a conversation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "role", rename_all = "lowercase")]
pub enum Message {
    System(SystemMessage),
    User(UserMessage),
    Assistant(AssistantMessage),
    Tool(ToolMessage),
}

impl Message {
    pub fn system(content: impl Into<String>) -> Self {
        Self::System(SystemMessage {
            content: content.into(),
            provider_options: None,
        })
    }

    pub fn user(content: impl Into<String>) -> Self {
        Self::User(UserMessage {
            content: vec![ContentPart::Text(TextContent {
                text: content.into(),
                provider_options: None,
            })],
            provider_options: None,
        })
    }

    pub fn assistant(content: impl Into<String>) -> Self {
        Self::Assistant(AssistantMessage {
            content: vec![ContentPart::Text(TextContent {
                text: content.into(),
                provider_options: None,
            })],
            provider_options: None,
        })
    }

    pub fn user_with_parts(content: Vec<ContentPart>) -> Self {
        Self::User(UserMessage {
            content,
            provider_options: None,
        })
    }

    pub fn assistant_with_parts(content: Vec<ContentPart>) -> Self {
        Self::Assistant(AssistantMessage {
            content,
            provider_options: None,
        })
    }
}

/// System message providing instructions to the model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemMessage {
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

/// User message with text or multimedia content.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserMessage {
    pub content: Vec<ContentPart>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

/// Assistant message with text, reasoning, or tool calls.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AssistantMessage {
    pub content: Vec<ContentPart>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

/// Tool message with responses from tool execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolMessage {
    pub content: Vec<ToolContent>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

/// Content parts in a message.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ContentPart {
    Text(TextContent),
    Image(ImageContent),
    File(FileContent),
    Reasoning(ReasoningContent),
    ToolCall(ToolCallContent),
    ToolResult(ToolContent),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TextContent {
    pub text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ImageContent {
    pub data: String,
    pub media_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileContent {
    pub data: String,
    pub media_type: String,
    pub filename: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReasoningContent {
    pub text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolCallContent {
    pub tool_call_id: String,
    pub tool_name: String,
    pub input: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub provider_options: Option<serde_json::Value>,
}

/// Content in a tool message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolContent {
    pub tool_call_id: String,
    pub output: ToolOutput,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ToolOutput {
    Text { value: String },
    Json { value: serde_json::Value },
}
