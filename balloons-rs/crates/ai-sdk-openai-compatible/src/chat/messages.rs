//! Convert prompts to OpenAI-compatible messages.

use crate::types::{AssistantMessage, Message, Prompt, SystemMessage, ToolMessage, UserMessage};
use crate::chat::types::{
    AssistantMessage as ApiAssistantMessage, ChatMessage, FunctionCall,
    SystemMessage as ApiSystemMessage, ToolCall, ToolMessage as ApiToolMessage,
    UserContentPart, UserMessage as ApiUserMessage,
};

/// Convert internal prompt to OpenAI-compatible chat messages.
pub fn convert_to_chat_messages(prompt: &Prompt) -> Vec<ChatMessage> {
    prompt.messages.iter().map(convert_message).collect()
}

fn convert_message(message: &Message) -> ChatMessage {
    match message {
        Message::System(msg) => convert_system_message(msg),
        Message::User(msg) => convert_user_message(msg),
        Message::Assistant(msg) => convert_assistant_message(msg),
        Message::Tool(msg) => convert_tool_message(msg),
    }
}

fn convert_system_message(msg: &SystemMessage) -> ChatMessage {
    ChatMessage::System(ApiSystemMessage {
        content: msg.content.clone(),
    })
}

fn convert_user_message(msg: &UserMessage) -> ChatMessage {
    if msg.content.len() == 1 {
        if let crate::types::prompt::ContentPart::Text(text) = &msg.content[0] {
            return ChatMessage::User(ApiUserMessage::Simple {
                content: text.text.clone(),
            });
        }
    }

    let content = msg
        .content
        .iter()
        .filter_map(|part| match part {
            crate::types::prompt::ContentPart::Text(t) => Some(UserContentPart::Text {
                text: t.text.clone(),
            }),
            crate::types::prompt::ContentPart::Image(i) => Some(UserContentPart::ImageUrl {
                image_url: crate::chat::types::ImageUrl {
                    url: format!("data:{};base64,{}", i.media_type, i.data),
                    detail: None,
                },
            }),
            crate::types::prompt::ContentPart::File(_) => {
                // TODO: Handle file parts
                Some(UserContentPart::Text {
                    text: "[file content]".to_string(),
                })
            }
            // Ignore reasoning and tool calls in user messages
            crate::types::prompt::ContentPart::Reasoning(_) |
            crate::types::prompt::ContentPart::ToolCall(_) => None,
        })
        .collect();

    ChatMessage::User(ApiUserMessage::Complex { content })
}

fn convert_assistant_message(msg: &AssistantMessage) -> ChatMessage {
    let mut text = String::new();
    let mut tool_calls = Vec::new();
    let mut reasoning = String::new();

    for part in &msg.content {
        match part {
            crate::types::prompt::ContentPart::Text(t) => {
                text.push_str(&t.text);
            }
            crate::types::prompt::ContentPart::Reasoning(r) => {
                reasoning.push_str(&r.text);
            }
            crate::types::prompt::ContentPart::ToolCall(t) => {
                tool_calls.push(ToolCall {
                    id: t.tool_call_id.clone(),
                    tool_type: "function".to_string(),
                    function: FunctionCall {
                        name: t.tool_name.clone(),
                        arguments: serde_json::to_string(&t.input).unwrap_or_default(),
                    },
                });
            }
            crate::types::prompt::ContentPart::Image(_) |
            crate::types::prompt::ContentPart::File(_) => {
                // Ignore images/files in assistant messages
            }
        }
    }

    ChatMessage::Assistant(ApiAssistantMessage {
        content: if tool_calls.is_empty() {
            Some(text)
        } else {
            Some(text).filter(|s| !s.is_empty())
        },
        tool_calls: if tool_calls.is_empty() {
            None
        } else {
            Some(tool_calls)
        },
        reasoning_content: if reasoning.is_empty() {
            None
        } else {
            Some(reasoning)
        },
    })
}

fn convert_tool_message(msg: &ToolMessage) -> ChatMessage {
    ChatMessage::Tool(ApiToolMessage {
        tool_call_id: msg.content[0].tool_call_id.clone(),
        content: match &msg.content[0].output {
            crate::types::ToolOutput::Text { value } => value.clone(),
            crate::types::ToolOutput::Json { value } => {
                serde_json::to_string(value).unwrap_or_default()
            }
        },
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_user_message() {
        let prompt = Prompt::with_user("Hello");
        let messages = convert_to_chat_messages(&prompt);
        assert_eq!(messages.len(), 1);
        assert!(matches!(messages[0], ChatMessage::User(_)));
    }

    #[test]
    fn test_system_message() {
        let mut prompt = Prompt::with_system("You are helpful");
        prompt.messages.push(Message::user("Hi"));
        let messages = convert_to_chat_messages(&prompt);
        assert_eq!(messages.len(), 2);
        assert!(matches!(messages[0], ChatMessage::System(_)));
    }
}
