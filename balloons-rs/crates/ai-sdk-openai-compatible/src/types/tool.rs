//! Tool types for tool calling.

use serde::{Deserialize, Serialize};
use schemars::JsonSchema;

/// Tool definition for the model.
#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub struct ToolDefinition {
    pub name: String,
    pub description: Option<String>,
    pub parameters: serde_json::Value,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub strict: Option<bool>,
}

/// Tool choice strategy.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ToolChoice {
    /// No tool calls.
    None,
    /// Auto-select tools.
    Auto,
    /// Required tool call.
    Required,
    /// Specific tool to call.
    Tool {
        #[serde(rename = "type")]
        tool_type: String,
        function: ToolFunction,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolFunction {
    pub name: String,
}

/// A tool call from the model.
#[derive(Debug, Clone)]
pub struct ToolCall {
    pub tool_call_id: String,
    pub tool_name: String,
    pub input: serde_json::Value,
}

impl ToolCall {
    pub fn new(tool_name: impl Into<String>, input: serde_json::Value) -> Self {
        Self {
            tool_call_id: uuid::Uuid::new_v4().to_string(),
            tool_name: tool_name.into(),
            input,
        }
    }
}
