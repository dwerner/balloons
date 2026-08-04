//! Python bindings for ai-sdk-openai-compatible.
//!
//! Provides async Python access to OpenAI-compatible LLM APIs.

use pyo3::prelude::*;
use pyo3::types::PyAny;
use pyo3_async_runtimes::tokio::future_into_py;


use ::ai_sdk_openai_compatible::{
    create_chat_model, create_completion_model, create_embedding_model,
    CallOptions, LanguageModel, Prompt, ProviderConfig,
};
use async_lock;

// ============================================================================
// Python Exceptions
// ============================================================================

#[pyclass]
#[derive(Debug)]
struct AIError {
    message: String,
}

#[pymethods]
impl AIError {
    fn __str__(&self) -> String {
        self.message.clone()
    }
}

impl From<::ai_sdk_openai_compatible::Error> for AIError {
    fn from(e: ::ai_sdk_openai_compatible::Error) -> Self {
        AIError {
            message: e.to_string(),
        }
    }
}

impl From<AIError> for PyErr {
    fn from(e: AIError) -> PyErr {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.message)
    }
}

// ============================================================================
// Result Types
// ============================================================================

#[pyclass(get_all, from_py_object)]
#[derive(Debug, Clone)]
struct Usage {
    input_tokens: u32,
    output_tokens: u32,
    total_tokens: u32,
}

impl From<::ai_sdk_openai_compatible::Usage> for Usage {
    fn from(u: ::ai_sdk_openai_compatible::Usage) -> Self {
        Self {
            input_tokens: u.input_tokens,
            output_tokens: u.output_tokens,
            total_tokens: u.total_tokens,
        }
    }
}

#[pyclass(get_all, from_py_object)]
#[derive(Debug, Clone)]
struct ToolCall {
    id: String,
    name: String,
    arguments: JsonValue,
}

impl From<::ai_sdk_openai_compatible::ToolCall> for ToolCall {
    fn from(tc: ::ai_sdk_openai_compatible::ToolCall) -> Self {
        Self {
            id: tc.tool_call_id,
            name: tc.tool_name,
            arguments: JsonValue(tc.input),
        }
    }
}

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
pub struct JsonValue(pub serde_json::Value);

#[pymethods]
impl JsonValue {
    #[new]
    fn new(value: &Bound<'_, PyAny>) -> PyResult<Self> {
        // Convert Python value to serde_json::Value
        let json_str = value.call_method1("__json__", ())
            .or_else(|_| {
                // If no __json__ method, use json.dumps
                let json_module = value.py().import("json")?;
                json_module.call_method1("dumps", (value,))
            })?;
        
        let json_str = json_str.extract::<String>()?;
        let json_value: serde_json::Value = serde_json::from_str(&json_str)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        
        Ok(JsonValue(json_value))
    }

    fn __repr__(&self) -> String {
        format!("JsonValue({})", self.0)
    }

    fn __str__(&self) -> String {
        self.0.to_string()
    }

    fn is_object(&self) -> bool {
        matches!(self.0, serde_json::Value::Object(_))
    }

    fn is_array(&self) -> bool {
        matches!(self.0, serde_json::Value::Array(_))
    }

    fn is_string(&self) -> bool {
        matches!(self.0, serde_json::Value::String(_))
    }

    fn is_number(&self) -> bool {
        matches!(self.0, serde_json::Value::Number(_))
    }

    fn is_bool(&self) -> bool {
        matches!(self.0, serde_json::Value::Bool(_))
    }

    fn is_null(&self) -> bool {
        matches!(self.0, serde_json::Value::Null)
    }

    fn as_string(&self) -> Option<&str> {
        self.0.as_str()
    }

    fn as_number(&self) -> Option<f64> {
        self.0.as_f64()
    }

    fn as_bool(&self) -> Option<bool> {
        self.0.as_bool()
    }

    fn keys(&self, _py: Python<'_>) -> PyResult<Vec<String>> {
        if let serde_json::Value::Object(map) = &self.0 {
            Ok(map.keys().cloned().collect())
        } else {
            Err(pyo3::exceptions::PyTypeError::new_err("Not a JSON object"))
        }
    }

    fn get(&self, _py: Python<'_>, key: &str) -> PyResult<JsonValue> {
        if let serde_json::Value::Object(map) = &self.0 {
            if let Some(v) = map.get(key) {
                Ok(JsonValue(v.clone()))
            } else {
                Err(pyo3::exceptions::PyKeyError::new_err(key.to_string()))
            }
        } else {
            Err(pyo3::exceptions::PyTypeError::new_err("Not a JSON object"))
        }
    }

    fn __len__(&self) -> PyResult<usize> {
        match &self.0 {
            serde_json::Value::Array(arr) => Ok(arr.len()),
            serde_json::Value::Object(map) => Ok(map.len()),
            _ => Err(pyo3::exceptions::PyTypeError::new_err("Object has no length")),
        }
    }

   /// Deep merge two JSON values. If both are objects, merge keys recursively.
    /// If types differ or not objects, other wins.
    fn merge(&self, other: &JsonValue) -> PyResult<JsonValue> {
        match (&self.0, &other.0) {
            (serde_json::Value::Object(a), serde_json::Value::Object(b)) => {
                let mut merged = a.clone();
                for (k, v) in b {
                    merged.insert(k.clone(), v.clone());
                }
                Ok(JsonValue(serde_json::Value::Object(merged)))
            }
            _ => Ok(other.clone()),
        }
    }

    /// Convert to native Python dict (for tool execution boundary)
    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        // Use serde_json's built-in conversion to Python via JSON string
        let json_str = self.0.to_string();
        let json_module = py.import("json")?;
        json_module.call_method1("loads", (json_str,))
    }
}

#[pyclass(get_all, from_py_object)]
#[derive(Debug, Clone)]
struct GenerateResult {
    text: Option<String>,
    reasoning: Option<String>,
    tool_calls: Vec<ToolCall>,
    usage: Usage,
    finish_reason: String,
    response_id: String,
}

// ============================================================================
// Completion Result Types
// ============================================================================

#[pyclass(get_all, from_py_object)]
#[derive(Debug, Clone)]
struct CompletionResult {
    text: String,
    usage: Usage,
    finish_reason: String,
}

// ============================================================================
// Embedding Result Types
// ============================================================================

#[pyclass(get_all, from_py_object)]
#[derive(Debug, Clone)]
struct EmbeddingResult {
    embeddings: Vec<Vec<f64>>,
    usage: Usage,
}

// ============================================================================
// Streaming Event Types (mirrors Rust SDK StreamPart)
// ============================================================================

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
enum StreamPart {
    TextDelta { delta: String },
    ReasoningDelta { delta: String },
    ToolCallStart { id: String, tool_name: String },
    ToolCallDelta { id: String, delta: String },
    ToolCallEnd { id: String },
    ToolCall { id: String, tool_name: String, arguments: String },
    Finish { usage: Option<Usage> },
    Done(),
}

// ============================================================================
// Tool Definition Type
// ============================================================================

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
struct ToolDefinition {
    #[pyo3(get)]
    name: String,
    #[pyo3(get)]
    description: Option<String>,
    #[pyo3(get)]
    parameters: String,  // JSON string
}

#[pymethods]
impl ToolDefinition {
    #[new]
    fn new(name: &str, description: Option<String>, parameters: &str) -> Self {
        Self {
            name: name.to_string(),
            description,
            parameters: parameters.to_string(),
        }
    }
}

// ============================================================================
// Chat Model
// ============================================================================

#[pyclass]
struct ChatModel {
    model: std::sync::Arc<::ai_sdk_openai_compatible::OpenAICompatibleChatModel>,
}

#[pymethods]
impl ChatModel {
    /// Generate a response from the chat model.
    ///
    /// Args:
    ///     messages: List of message dicts with 'role' and 'content' keys
    ///     max_tokens: Maximum tokens to generate
    ///     temperature: Sampling temperature (0.0-2.0)
    ///     tools: List of tool definitions (optional)
    ///
    /// Returns:
    ///     GenerateResult with text, reasoning, tool_calls, usage, and finish_reason
    fn generate<'py>(
        &'py self,
        py: Python<'py>,
        messages: Vec<Message>,
        max_tokens: Option<u32>,
        temperature: Option<f32>,
        tools: Option<Vec<ToolDefinition>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let model = self.model.clone();
        let prompt = convert_messages_to_prompt(messages);

        let mut options = CallOptions {
            max_tokens,
            temperature: Some(temperature.unwrap_or(0.7)),
            ..Default::default()
        };

        // Convert Python tool definitions to Rust format
        if let Some(py_tools) = tools {
            let rust_tools = py_tools
                .into_iter()
                .map(|py_tool| {
                    let params: serde_json::Value = serde_json::from_str(&py_tool.parameters)
                        .unwrap_or_else(|_| serde_json::json!({}));
                    ::ai_sdk_openai_compatible::ToolDefinition {
                        name: py_tool.name,
                        description: py_tool.description,
                        parameters: params,
                        strict: None,
                    }
                })
                .collect();
            options.tools = Some(rust_tools);
        }

        future_into_py(py, async move {
            let result = model.do_generate(prompt, options).await
                .map_err(|e| AIError { message: e.to_string() })?;

            Ok(GenerateResult {
                text: result.text,
                reasoning: result.reasoning,
                tool_calls: result.tool_calls.into_iter().map(Into::into).collect(),
                usage: result.usage.into(),
                finish_reason: format!("{:?}", result.finish_reason),
                response_id: result.response_id,
            })
        })
    }

    /// Stream a response from the chat model.
    ///
    /// Args:
    ///     messages: List of message dicts with 'role' and 'content' keys
    ///     max_tokens: Maximum tokens to generate
    ///     temperature: Sampling temperature (0.0-2.0)
    ///     tools: List of tool definitions (optional)
    ///     tool_choice: How the model chooses tools: "auto", "none", "required" (optional, default "auto")
    ///
    /// Returns:
    ///     Async generator yielding StreamChunk objects
    fn stream<'py>(
        &'py self,
        py: Python<'py>,
        messages: Vec<Message>,
        max_tokens: Option<u32>,
        temperature: Option<f32>,
        tools: Option<Vec<ToolDefinition>>,
        tool_choice: Option<String>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let model = self.model.clone();
        let prompt = convert_messages_to_prompt(messages);

        let mut options = CallOptions {
            max_tokens,
            temperature: Some(temperature.unwrap_or(0.7)),
            ..Default::default()
        };

        // Convert Python tool definitions to Rust format
        if let Some(py_tools) = tools {
            let rust_tools = py_tools
                .into_iter()
                .map(|py_tool| {
                    let params: serde_json::Value = serde_json::from_str(&py_tool.parameters)
                        .unwrap_or_else(|_| serde_json::json!({}));
                    ::ai_sdk_openai_compatible::ToolDefinition {
                        name: py_tool.name,
                        description: py_tool.description,
                        parameters: params,
                        strict: None,
                    }
                })
                .collect();
            options.tools = Some(rust_tools);
        }

        // Set tool_choice if provided
        if let Some(choice) = tool_choice {
            options.tool_choice = Some(match choice.as_str() {
                "none" => ::ai_sdk_openai_compatible::ToolChoice::None,
                "required" => ::ai_sdk_openai_compatible::ToolChoice::Required,
                _ => ::ai_sdk_openai_compatible::ToolChoice::Auto,
            });
        }

        future_into_py(py, async move {
            let stream = model.do_stream(prompt, options)
                .await
                .map_err(|e| AIError { message: e.to_string() })?;

            Ok(AsyncGenerator::new(stream))
        })
    }
}

// ============================================================================
// Completion Model
// ============================================================================

#[pyclass]
struct CompletionModel {
    model: std::sync::Arc<::ai_sdk_openai_compatible::OpenAICompatibleCompletionModel>,
}

#[pymethods]
impl CompletionModel {
    /// Generate a text completion.
    ///
    /// Args:
    ///     prompt: The prompt text
    ///     max_tokens: Maximum tokens to generate
    ///     temperature: Sampling temperature (0.0-2.0)
    ///
    /// Returns:
    ///     CompletionResult with text, usage, and finish_reason
    fn generate<'py>(
        &'py self,
        py: Python<'py>,
        prompt: &str,
        max_tokens: Option<u32>,
        temperature: Option<f32>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let model = self.model.clone();
        let prompt_obj = Prompt::with_user(prompt);

        let options = CallOptions {
            max_tokens,
            temperature: Some(temperature.unwrap_or(0.7)),
            ..Default::default()
        };

        future_into_py(py, async move {
            let result = model.do_generate(prompt_obj, options).await
                .map_err(|e| AIError { message: e.to_string() })?;

            Ok(CompletionResult {
                text: result.text.unwrap_or_default(),
                usage: result.usage.into(),
                finish_reason: format!("{:?}", result.finish_reason),
            })
        })
    }
}

// ============================================================================
// Embedding Model
// ============================================================================

#[pyclass]
struct EmbeddingModel {
    model: std::sync::Arc<::ai_sdk_openai_compatible::OpenAICompatibleEmbeddingModel>,
}

#[pymethods]
impl EmbeddingModel {
  /// Generate embeddings for text values.
    ///
    /// Args:
    ///     texts: List of text strings to embed
    ///     dimensions: Number of dimensions (optional)
    ///
    /// Returns:
    ///     EmbeddingResult with embeddings and usage
    fn embed<'py>(
        &'py self,
        py: Python<'py>,
        texts: Vec<String>,
        dimensions: Option<u32>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let model = self.model.clone();

        let mut options = ::ai_sdk_openai_compatible::EmbeddingOptions::default();
        if let Some(dim) = dimensions {
            options.dimensions = Some(dim);
        }

        future_into_py(py, async move {
            let result = model.do_embed(texts, options).await
                .map_err(|e| AIError { message: e.to_string() })?;

            let embeddings: Vec<Vec<f64>> = result.embeddings
                .into_iter()
                .map(|e| e.into_iter().map(|x| x as f64).collect())
                .collect();

            Ok(EmbeddingResult {
                embeddings,
                usage: result.usage.into(),
            })
        })
    }
}

// ============================================================================
// Provider Factory
// ============================================================================

/// Create a chat model from an OpenAI-compatible API.
///
/// Args:
///     base_url: Base URL of the API (e.g., "http://localhost:8000")
///     model_id: Model identifier (e.g., "qwen3.5")
///     api_key: Optional API key
///
/// Returns:
///     ChatModel instance
#[pyfunction]
fn create_chat_model_py(
    _py: Python,
    base_url: &str,
    model_id: &str,
    api_key: Option<String>,
) -> PyResult<ChatModel> {
    let mut config = ProviderConfig::new(base_url);
    if let Some(key) = api_key {
        config = config.with_api_key(key);
    }

    let model = create_chat_model(config, model_id)
        .map_err(|e| AIError { message: e.to_string() })?;

    Ok(ChatModel {
        model: std::sync::Arc::new(model),
    })
}

/// Create a completion model from an OpenAI-compatible API.
#[pyfunction]
fn create_completion_model_py(
    _py: Python,
    base_url: &str,
    model_id: &str,
    api_key: Option<String>,
) -> PyResult<CompletionModel> {
    let mut config = ProviderConfig::new(base_url);
    if let Some(key) = api_key {
        config = config.with_api_key(key);
    }

    let model = create_completion_model(config, model_id)
        .map_err(|e| AIError { message: e.to_string() })?;

    Ok(CompletionModel {
        model: std::sync::Arc::new(model),
    })
}

/// Create an embedding model from an OpenAI-compatible API.
#[pyfunction]
fn create_embedding_model_py(
    _py: Python,
    base_url: &str,
    model_id: &str,
    api_key: Option<String>,
) -> PyResult<EmbeddingModel> {
    let mut config = ProviderConfig::new(base_url);
    if let Some(key) = api_key {
        config = config.with_api_key(key);
    }

    let model = create_embedding_model(config, model_id)
        .map_err(|e| AIError { message: e.to_string() })?;

    Ok(EmbeddingModel {
        model: std::sync::Arc::new(model),
    })
}

// ============================================================================
// Helper Types
// ============================================================================

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
struct ImageContent {
    #[pyo3(get)]
    data: String,  // base64 encoded or URL
    #[pyo3(get)]
    media_type: String,
}

#[pymethods]
impl ImageContent {
    #[new]
    fn new(data: &str, media_type: &str) -> Self {
        Self {
            data: data.to_string(),
            media_type: media_type.to_string(),
        }
    }
}

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
struct ToolCallContent {
    #[pyo3(get)]
    tool_call_id: String,
    #[pyo3(get)]
    tool_name: String,
    #[pyo3(get)]
    input: String,  // JSON string
}

#[pymethods]
impl ToolCallContent {
    #[new]
    fn new(tool_call_id: &str, tool_name: &str, input: &str) -> Self {
        Self {
            tool_call_id: tool_call_id.to_string(),
            tool_name: tool_name.to_string(),
            input: input.to_string(),
        }
    }
}

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
struct ToolResultContent {
    #[pyo3(get)]
    tool_call_id: String,
    #[pyo3(get)]
    output: String,
}

#[pymethods]
impl ToolResultContent {
    #[new]
    fn new(tool_call_id: &str, output: &str) -> Self {
        Self {
            tool_call_id: tool_call_id.to_string(),
            output: output.to_string(),
        }
    }
}

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
struct ReasoningContent {
    #[pyo3(get)]
    text: String,
}

#[pymethods]
impl ReasoningContent {
    #[new]
    fn new(text: &str) -> Self {
        Self {
            text: text.to_string(),
        }
    }
}

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
enum ContentPart {
    Text { text: String },
    Image { image: ImageContent },
    Reasoning { reasoning: ReasoningContent },
    ToolCall { tool_call: ToolCallContent },
    ToolResult { tool_result: ToolResultContent },
}

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
struct Message {
    #[pyo3(get)]
    role: String,
    #[pyo3(get)]
    content: MessageContent,
}

#[pyclass(from_py_object)]
#[derive(Debug, Clone)]
enum MessageContent {
    Simple { text: String },
    Complex { parts: Vec<ContentPart> },
}

#[pymethods]
impl Message {
    #[new]
    #[pyo3(signature = (role, content, tool_call_id=None))]
    fn new(role: &str, content: &Bound<'_, PyAny>, tool_call_id: Option<String>) -> PyResult<Self> {
        let role_str = role.to_string();
        
        // For tool role with string content, create ToolResultContent
        if role_str == "tool" {
            if let Ok(text) = content.extract::<String>() {
                let tool_result = ToolResultContent::new(
                    &tool_call_id.unwrap_or_default(),
                    &text
                );
                return Ok(Self {
                    role: role_str,
                    content: MessageContent::Complex {
                        parts: vec![ContentPart::ToolResult { tool_result }],
                    },
                });
            }
        }
        
        // Check if content is a string (simple message)
        if content.is_instance_of::<pyo3::types::PyString>() {
            let text = content.extract::<String>()?;
            return Ok(Self {
                role: role_str,
                content: MessageContent::Simple { text },
            });
        }
        
        // Check if content is a list (complex message with parts)
        if content.is_instance_of::<pyo3::types::PyList>() {
            let parts_list = content.cast::<pyo3::types::PyList>()?;
            let mut parts = Vec::new();
            
            for part_obj in parts_list {
                let part_dict = part_obj.cast::<pyo3::types::PyDict>()?;
                let part_type = part_dict.get_item("type")?.unwrap().extract::<String>()?;
                
                match part_type.as_str() {
                    "text" => {
                        let text = part_dict.get_item("text")?.unwrap().extract::<String>()?;
                        parts.push(ContentPart::Text { text });
                    }
                    "image" => {
                        let image_data = part_dict.get_item("data")?.unwrap().extract::<String>()?;
                        let media_type = part_dict.get_item("media_type")?.unwrap().extract::<String>()?;
                        let image = ImageContent::new(&image_data, &media_type);
                        parts.push(ContentPart::Image { image });
                    }
                    "reasoning" => {
                        let text = part_dict.get_item("text")?.unwrap().extract::<String>()?;
                        let reasoning = ReasoningContent::new(&text);
                        parts.push(ContentPart::Reasoning { reasoning });
                    }
                    "tool_call" => {
                        let tool_call_id = part_dict.get_item("tool_call_id")?.unwrap().extract::<String>()?;
                        let tool_name = part_dict.get_item("tool_name")?.unwrap().extract::<String>()?;
                        let input = part_dict.get_item("input")?.unwrap().extract::<String>()?;
                        let tool_call = ToolCallContent::new(&tool_call_id, &tool_name, &input);
                        parts.push(ContentPart::ToolCall { tool_call });
                    }
                    "tool_result" => {
                        let tool_call_id = part_dict.get_item("tool_call_id")?.unwrap().extract::<String>()?;
                        let output = part_dict.get_item("output")?.unwrap().extract::<String>()?;
                        let tool_result = ToolResultContent::new(&tool_call_id, &output);
                        parts.push(ContentPart::ToolResult { tool_result });
                    }
                    _ => {}
                }
            }
            
            return Ok(Self {
                role: role_str,
                content: MessageContent::Complex { parts },
            });
        }
        
        Err(pyo3::exceptions::PyValueError::new_err(
            "Content must be a string or list of content parts"
        ))
    }
}

fn convert_messages_to_prompt(messages: Vec<Message>) -> Prompt {
    let mut prompt = Prompt::new(vec![]);
    
    for msg in messages {
        match msg.role.as_str() {
            "system" => {
                let content = match &msg.content {
                    MessageContent::Simple { text } => text.clone(),
                    MessageContent::Complex { parts } => {
                        // For system messages, concatenate all text parts
                        parts.iter()
                            .filter_map(|p| match p {
                                ContentPart::Text { text } => Some(text.clone()),
                                _ => None,
                            })
                            .collect::<Vec<_>>()
                            .join("\n")
                    }
                };
                prompt.messages.push(::ai_sdk_openai_compatible::Message::system(&content));
            }
            "user" => {
                match &msg.content {
                    MessageContent::Simple { text } => {
                        prompt.messages.push(::ai_sdk_openai_compatible::Message::user(text));
                    }
                    MessageContent::Complex { parts } => {
                        let mut content_parts = Vec::new();
                        
                        for part in parts {
                            match part {
                                ContentPart::Text { text } => {
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::Text(
                                            ::ai_sdk_openai_compatible::types::prompt::TextContent {
                                                text: text.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                ContentPart::Image { image } => {
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::Image(
                                            ::ai_sdk_openai_compatible::types::prompt::ImageContent {
                                                data: image.data.clone(),
                                                media_type: image.media_type.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                ContentPart::Reasoning { reasoning } => {
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::Reasoning(
                                            ::ai_sdk_openai_compatible::types::prompt::ReasoningContent {
                                                text: reasoning.text.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                ContentPart::ToolCall { tool_call } => {
                                    let input: serde_json::Value = serde_json::from_str(&tool_call.input)
                                        .unwrap_or_else(|_| serde_json::json!({}));
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::ToolCall(
                                            ::ai_sdk_openai_compatible::types::prompt::ToolCallContent {
                                                tool_call_id: tool_call.tool_call_id.clone(),
                                                tool_name: tool_call.tool_name.clone(),
                                                input,
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                ContentPart::ToolResult { tool_result } => {
                                    let output = if tool_result.output.starts_with('{') || tool_result.output.starts_with('[') {
                                        ::ai_sdk_openai_compatible::types::ToolOutput::Json {
                                            value: serde_json::from_str(&tool_result.output).unwrap_or_else(|_| serde_json::json!({})),
                                        }
                                    } else {
                                        ::ai_sdk_openai_compatible::types::ToolOutput::Text {
                                            value: tool_result.output.clone(),
                                        }
                                    };
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::ToolResult(
                                            ::ai_sdk_openai_compatible::types::prompt::ToolContent {
                                                tool_call_id: tool_result.tool_call_id.clone(),
                                                output,
                                            }
                                        )
                                    );
                                }
                            }
                        }
                        
                        prompt.messages.push(::ai_sdk_openai_compatible::Message::user_with_parts(content_parts));
                    }
                }
            }
            "assistant" => {
                match &msg.content {
                    MessageContent::Simple { text } => {
                        prompt.messages.push(::ai_sdk_openai_compatible::Message::assistant(text));
                    }
                    MessageContent::Complex { parts } => {
                        let mut content_parts = Vec::new();
                        
                        for part in parts {
                            match part {
                                ContentPart::Text { text } => {
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::Text(
                                            ::ai_sdk_openai_compatible::types::prompt::TextContent {
                                                text: text.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                ContentPart::Reasoning { reasoning } => {
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::Reasoning(
                                            ::ai_sdk_openai_compatible::types::prompt::ReasoningContent {
                                                text: reasoning.text.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                ContentPart::ToolCall { tool_call } => {
                                    let input: serde_json::Value = serde_json::from_str(&tool_call.input)
                                        .unwrap_or_else(|_| serde_json::json!({}));
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::ToolCall(
                                            ::ai_sdk_openai_compatible::types::prompt::ToolCallContent {
                                                tool_call_id: tool_call.tool_call_id.clone(),
                                                tool_name: tool_call.tool_name.clone(),
                                                input,
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                ContentPart::ToolResult { tool_result } => {
                                    let output = if tool_result.output.starts_with('{') || tool_result.output.starts_with('[') {
                                        ::ai_sdk_openai_compatible::types::ToolOutput::Json {
                                            value: serde_json::from_str(&tool_result.output).unwrap_or_else(|_| serde_json::json!({})),
                                        }
                                    } else {
                                        ::ai_sdk_openai_compatible::types::ToolOutput::Text {
                                            value: tool_result.output.clone(),
                                        }
                                    };
                                    content_parts.push(
                                        ::ai_sdk_openai_compatible::types::prompt::ContentPart::ToolResult(
                                            ::ai_sdk_openai_compatible::types::prompt::ToolContent {
                                                tool_call_id: tool_result.tool_call_id.clone(),
                                                output,
                                            }
                                        )
                                    );
                                }
                                ContentPart::Image { .. } => {
                                    // Ignore images in assistant messages
                                }
                            }
                        }
                        
                        if !content_parts.is_empty() {
                            prompt.messages.push(::ai_sdk_openai_compatible::Message::assistant_with_parts(content_parts));
                        }
                    }
                }
            }
            _ => {}
        }
    }
    
    prompt
}

// ============================================================================
// Async Generator for Streaming
// ============================================================================

#[pyclass]
struct AsyncGenerator {
    stream: Option<std::sync::Arc<async_lock::Mutex<::ai_sdk_openai_compatible::LanguageModelStream>>>,
}

impl AsyncGenerator {
    fn new(stream: ::ai_sdk_openai_compatible::LanguageModelStream) -> Self {
        Self {
            stream: Some(std::sync::Arc::new(async_lock::Mutex::new(stream))),
        }
    }
}

#[pymethods]
impl AsyncGenerator {
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __anext__<'a>(slf: PyRef<'a, Self>, py: Python<'a>) -> PyResult<Option<Bound<'a, PyAny>>> {
        let stream = slf.stream.clone().unwrap();
        
        let future = future_into_py(py, async move {
            use futures::StreamExt;
            
            loop {
                let mut stream_guard = stream.lock().await;
                match stream_guard.next().await {
                    Some(Ok(::ai_sdk_openai_compatible::StreamPart::TextDelta { delta })) => {
                        return Ok(StreamPart::TextDelta { delta });
                    }
                    Some(Ok(::ai_sdk_openai_compatible::StreamPart::ReasoningDelta { delta })) => {
                        return Ok(StreamPart::ReasoningDelta { delta });
                    }
                    Some(Ok(::ai_sdk_openai_compatible::StreamPart::ToolCallStart { id, tool_name })) => {
                        return Ok(StreamPart::ToolCallStart {
                            id,
                            tool_name,
                        });
                    }
                    Some(Ok(::ai_sdk_openai_compatible::StreamPart::ToolCallDelta { id, delta })) => {
                        return Ok(StreamPart::ToolCallDelta {
                            id,
                            delta,
                        });
                    }
                    Some(Ok(::ai_sdk_openai_compatible::StreamPart::ToolCallEnd { id })) => {
                        return Ok(StreamPart::ToolCallEnd { id });
                    }
                    Some(Ok(::ai_sdk_openai_compatible::StreamPart::ToolCall { id, tool_name, arguments })) => {
                        return Ok(StreamPart::ToolCall {
                            id,
                            tool_name,
                            arguments,
                        });
                    }
                    Some(Ok(::ai_sdk_openai_compatible::StreamPart::Finish { reason: _, usage })) => {
                        return Ok(StreamPart::Finish {
                            usage: usage.map(Into::into),
                        });
                    }
                    Some(Err(e)) => return Err(AIError { message: e.to_string() }.into()),
                    None => return Ok(StreamPart::Done()),
                }
            }
        });
        
        future.map(|f| Some(f))
    }
}

// ============================================================================
// Module Definition
// ============================================================================

#[pymodule]
fn ai_sdk_openai_compatible_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ChatModel>()?;
    m.add_class::<CompletionModel>()?;
    m.add_class::<EmbeddingModel>()?;
    m.add_class::<Message>()?;
    m.add_class::<MessageContent>()?;
    m.add_class::<ContentPart>()?;
    m.add_class::<ImageContent>()?;
    m.add_class::<ToolCallContent>()?;
    m.add_class::<ToolResultContent>()?;
    m.add_class::<ReasoningContent>()?;
    m.add_class::<ToolDefinition>()?;
    m.add_class::<Usage>()?;
    m.add_class::<ToolCall>()?;
    m.add_class::<JsonValue>()?;
    m.add_class::<GenerateResult>()?;
    m.add_class::<CompletionResult>()?;
    m.add_class::<EmbeddingResult>()?;
    m.add_class::<StreamPart>()?;
    m.add_function(wrap_pyfunction!(create_chat_model_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_completion_model_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_embedding_model_py, m)?)?;
    m.add("AIError", m.py().get_type::<AIError>())?;
    
    Ok(())
}
