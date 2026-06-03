//! Tool preparation and handling.

use crate::types::{ToolCall, ToolChoice, ToolDefinition};
use crate::chat::types::{
    SpecificToolFunction, Tool as ApiTool, ToolCall as ApiToolCall,
    ToolChoice as ApiToolChoice, ToolFunction,
};

/// Prepare tools for API request.
pub fn prepare_tools(tools: &[ToolDefinition]) -> Vec<ApiTool> {
    tools
        .iter()
        .map(|tool| ApiTool::Function {
            function: ToolFunction {
                name: tool.name.clone(),
                description: tool.description.clone(),
                parameters: tool.parameters.clone(),
            },
        })
        .collect()
}

/// Convert tool choice to API format.
pub fn prepare_tool_choice(tool_choice: &ToolChoice) -> Option<ApiToolChoice> {
    match tool_choice {
        ToolChoice::None => Some(ApiToolChoice::None),
        ToolChoice::Auto => Some(ApiToolChoice::Auto),
        ToolChoice::Required => Some(ApiToolChoice::Required),
        ToolChoice::Tool { tool_type: _, function } => Some(ApiToolChoice::Specific {
            tool_type: "function".to_string(),
            function: SpecificToolFunction {
                name: function.name.clone(),
            },
        }),
    }
}

/// Parse tool calls from API response.
pub fn parse_tool_calls(tool_calls: &[ApiToolCall]) -> Vec<ToolCall> {
    tool_calls
        .iter()
        .map(|call| ToolCall {
            tool_call_id: call.id.clone(),
            tool_name: call.function.name.clone(),
            input: serde_json::from_str(&call.function.arguments)
                .unwrap_or_else(|_| serde_json::json!({})),
        })
        .collect()
}
