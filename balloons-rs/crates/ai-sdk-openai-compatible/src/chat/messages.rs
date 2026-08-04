//! Convert prompts to OpenAI-compatible messages.

use crate::types::{AssistantMessage, Message, Prompt, SystemMessage, ToolMessage, UserMessage};
use crate::chat::types::{
    AssistantMessage as ApiAssistantMessage, ChatMessage, FunctionCall,
    SystemMessage as ApiSystemMessage, ToolCall, ToolMessage as ApiToolMessage,
    UserContentPart, UserMessage as ApiUserMessage,
};

/// Convert internal prompt to OpenAI-compatible chat messages.
pub fn convert_to_chat_messages(prompt: &Prompt) -> Result<Vec<ChatMessage>, crate::Error> {
    prompt.messages
        .iter()
        .map(|m| convert_message(m).map_err(|e| crate::Error::InvalidResponse(e)))
        .collect()
}

fn convert_message(message: &Message) -> Result<ChatMessage, String> {
    match message {
        Message::System(msg) => Ok(convert_system_message(msg)),
        Message::User(msg) => convert_user_message(msg),
        Message::Assistant(msg) => Ok(convert_assistant_message(msg)),
        Message::Tool(msg) => Ok(convert_tool_message(msg)),
    }
}

fn convert_system_message(msg: &SystemMessage) -> ChatMessage {
    ChatMessage::System(ApiSystemMessage {
        content: msg.content.clone(),
    })
}

fn convert_user_message(msg: &UserMessage) -> Result<ChatMessage, String> {
    if msg.content.len() == 1 {
        if let crate::types::prompt::ContentPart::Text(text) = &msg.content[0] {
            return Ok(ChatMessage::User(ApiUserMessage::Simple {
                content: text.text.clone(),
            }));
        }
    }

    let mut content = Vec::new();
    for part in &msg.content {
        match part {
            crate::types::prompt::ContentPart::Text(t) => {
                content.push(UserContentPart::Text {
                    text: t.text.clone(),
                });
            }
            crate::types::prompt::ContentPart::Image(i) => {
                content.push(UserContentPart::ImageUrl {
                    image_url: crate::chat::types::ImageUrl {
                        url: format!("data:{};base64,{}", i.media_type, i.data),
                        detail: None,
                    },
                });
            }
            crate::types::prompt::ContentPart::File(_) => {
                // TODO: Handle file parts properly
                content.push(UserContentPart::Text {
                    text: "[file content]".to_string(),
                });
            }
            crate::types::prompt::ContentPart::Reasoning(_) => {
                return Err("Reasoning content is not valid in user messages".to_string());
            }
            crate::types::prompt::ContentPart::ToolCall(_) => {
                return Err("Tool calls are not valid in user messages".to_string());
            }
            crate::types::prompt::ContentPart::ToolResult(_) => {
                return Err("Tool results are not valid in user messages".to_string());
            }
        }
    }

    Ok(ChatMessage::User(ApiUserMessage::Complex { content }))
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
            crate::types::prompt::ContentPart::File(_) |
            crate::types::prompt::ContentPart::ToolResult(_) => {
                // Ignore images/files/tool results in assistant messages
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
        let messages = convert_to_chat_messages(&prompt).unwrap();
        assert_eq!(messages.len(), 1);
        assert!(matches!(messages[0], ChatMessage::User(_)));
    }

    #[test]
    fn test_system_message() {
        let mut prompt = Prompt::with_system("You are helpful");
        prompt.messages.push(Message::user("Hi"));
        let messages = convert_to_chat_messages(&prompt).unwrap();
        assert_eq!(messages.len(), 2);
        assert!(matches!(messages[0], ChatMessage::System(_)));
    }

    #[test]
    fn test_invalid_user_message_with_tool_call() {
        use crate::types::prompt::{ContentPart, ToolCallContent};
        use serde_json::json;
        
        let mut prompt = Prompt::new(vec![]);
        prompt.messages.push(Message::user_with_parts(vec![
            ContentPart::ToolCall(ToolCallContent {
                tool_call_id: "call_1".to_string(),
                tool_name: "test".to_string(),
                input: json!({}),
                provider_options: None,
            })
        ]));
        
        let result = convert_to_chat_messages(&prompt);
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("Tool calls"));
    }

    #[test]
    fn test_invalid_user_message_with_tool_result() {
        use crate::types::prompt::{ContentPart, ToolContent};
        
        let mut prompt = Prompt::new(vec![]);
        prompt.messages.push(Message::user_with_parts(vec![
            ContentPart::ToolResult(ToolContent {
                tool_call_id: "call_1".to_string(),
                output: crate::types::ToolOutput::Text { value: "result".to_string() },
            })
        ]));
        
        let result = convert_to_chat_messages(&prompt);
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("Tool results"));
    }

    #[test]
    fn test_invalid_user_message_with_reasoning() {
        use crate::types::prompt::{ContentPart, ReasoningContent};
        
        let mut prompt = Prompt::new(vec![]);
        prompt.messages.push(Message::user_with_parts(vec![
            ContentPart::Reasoning(ReasoningContent {
                text: "thinking".to_string(),
                provider_options: None,
            })
        ]));
        
        let result = convert_to_chat_messages(&prompt);
        assert!(result.is_err());
        let err = result.unwrap_err().to_string();
        assert!(err.contains("Reasoning"));
    }
}
