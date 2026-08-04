//! Core types for the OpenAI-compatible provider.

pub mod content;
pub mod finish_reason;
pub mod prompt;
pub mod tool;
pub mod usage;

pub use finish_reason::*;
pub use prompt::*;
pub use tool::*;
pub use usage::*;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

/// Call options for language model requests.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CallOptions {
    /// Maximum number of tokens to generate.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<u32>,

    /// Temperature for sampling.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f32>,

    /// Top-p sampling parameter.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub top_p: Option<f32>,

    /// Frequency penalty.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub frequency_penalty: Option<f32>,

    /// Presence penalty.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub presence_penalty: Option<f32>,

    /// Seed for reproducible outputs.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub seed: Option<u64>,

    /// Stop sequences.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stop: Option<Vec<String>>,

    /// Number of completions to generate.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub n: Option<u32>,

    /// Tools available for tool calling.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tools: Option<Vec<ToolDefinition>>,

    /// Tool choice strategy.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_choice: Option<ToolChoice>,

    /// Response format for structured outputs.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub response_format: Option<ResponseFormat>,
}

/// Response format for structured outputs.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResponseFormat {
    Text,
    JsonObject,
    JsonSchema {
        #[serde(rename = "json_schema")]
        json_schema: JsonSchema,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JsonSchema {
    pub name: String,
    pub description: Option<String>,
    pub schema: serde_json::Value,
    pub strict: Option<bool>,
}

/// Result from a non-streaming generate call.
#[derive(Debug, Clone)]
pub struct GenerateResult {
    pub response_id: String,
    pub text: Option<String>,
    pub reasoning: Option<String>,
    pub tool_calls: Vec<ToolCall>,
    pub usage: Usage,
    pub finish_reason: FinishReason,
    pub provider_metadata: serde_json::Value,
}

/// Result from a streaming generate call.
#[derive(Debug)]
pub struct StreamResult {
    pub response_id: Option<String>,
    pub usage: Option<Usage>,
    pub provider_metadata: serde_json::Value,
}

/// A stream of parts from a streaming response.
pub type LanguageModelStream = std::pin::Pin<
    Box<dyn futures::Stream<Item = Result<StreamPart, crate::Error>> + Send>,
>;

/// Individual parts of a streaming response.
#[derive(Debug)]
pub enum StreamPart {
    TextDelta { delta: String },
    ReasoningDelta { delta: String },
    ToolCallStart { id: String, tool_name: String },
    ToolCallDelta { id: String, delta: String },
    ToolCallEnd { id: String },
    ToolCall { id: String, tool_name: String, arguments: String },
    Finish { reason: FinishReason, usage: Option<Usage> },
}

/// Language model trait for async generation and streaming.
#[async_trait]
pub trait LanguageModel: Send + Sync {
    /// Provider identifier.
    fn provider(&self) -> &str;

    /// Model identifier.
    fn model_id(&self) -> &str;

    /// Generate a non-streaming response.
    async fn do_generate(
        &self,
        prompt: Prompt,
        options: CallOptions,
    ) -> Result<GenerateResult, crate::Error>;

    /// Generate a streaming response.
    async fn do_stream(
        &self,
        prompt: Prompt,
        options: CallOptions,
    ) -> Result<LanguageModelStream, crate::Error>;
}
