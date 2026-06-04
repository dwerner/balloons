//! Python bindings for ai-sdk-openai-compatible.
//!
//! Provides async Python access to OpenAI-compatible LLM APIs.

use pyo3::prelude::*;
use pyo3_async_runtimes::tokio::future_into_py;

use ai_sdk_openai_compatible::{
    create_chat_model, create_completion_model, create_embedding_model,
    CallOptions, EmbeddingOptions, LanguageModel, Prompt, ProviderConfig,
};

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

impl From<ai_sdk_openai_compatible::Error> for AIError {
    fn from(e: ai_sdk_openai_compatible::Error) -> Self {
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
// Python Tool Definition Type
// ============================================================================

#[pyclass]
#[derive(Debug, Clone)]
struct PyToolDefinition {
    #[pyo3(get)]
    name: String,
    #[pyo3(get)]
    description: Option<String>,
    #[pyo3(get)]
    parameters: String,  // JSON string
}

#[pymethods]
impl PyToolDefinition {
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
    model: std::sync::Arc<ai_sdk_openai_compatible::OpenAICompatibleChatModel>,
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
    ///     dict with 'text', 'usage', and 'finish_reason' keys
    fn generate<'py>(
        &'py self,
        py: Python<'py>,
        messages: Vec<PyMessage>,
        max_tokens: Option<u32>,
        temperature: Option<f32>,
        tools: Option<Vec<PyToolDefinition>>,
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
                    ai_sdk_openai_compatible::ToolDefinition {
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

            let mut response = serde_json::json!({
                "text": result.text.unwrap_or_default(),
                "usage": {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "total_tokens": result.usage.total_tokens,
                },
                "finish_reason": format!("{:?}", result.finish_reason),
            });

            if let Some(ref reasoning) = result.reasoning {
                response["reasoning"] = serde_json::json!(reasoning);
            }

            // Add tool calls if present
            if !result.tool_calls.is_empty() {
                let tool_calls: Vec<_> = result.tool_calls
                    .iter()
                    .map(|tc| {
                        serde_json::json!({
                            "id": tc.tool_call_id,
                            "name": tc.tool_name,
                            "arguments": tc.input,
                        })
                    })
                    .collect();
                response["tool_calls"] = serde_json::json!(tool_calls);
            }

            serde_json::to_string(&response)
                .map_err(|e| AIError { message: e.to_string() }.into())
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
    ///     Async generator yielding text deltas
    fn stream<'py>(
        &'py self,
        py: Python<'py>,
        messages: Vec<PyMessage>,
        max_tokens: Option<u32>,
        temperature: Option<f32>,
        tools: Option<Vec<PyToolDefinition>>,
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
                    ai_sdk_openai_compatible::ToolDefinition {
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
                "none" => ai_sdk_openai_compatible::ToolChoice::None,
                "required" => ai_sdk_openai_compatible::ToolChoice::Required,
                _ => ai_sdk_openai_compatible::ToolChoice::Auto,
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
    model: std::sync::Arc<ai_sdk_openai_compatible::OpenAICompatibleCompletionModel>,
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
    ///     dict with 'text', 'usage', and 'finish_reason' keys
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

            let response = serde_json::json!({
                "text": result.text.unwrap_or_default(),
                "usage": {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "total_tokens": result.usage.total_tokens,
                },
                "finish_reason": format!("{:?}", result.finish_reason),
            });

            serde_json::to_string(&response)
                .map_err(|e| AIError { message: e.to_string() }.into())
        })
    }
}

// ============================================================================
// Embedding Model
// ============================================================================

#[pyclass]
struct EmbeddingModel {
    model: std::sync::Arc<ai_sdk_openai_compatible::OpenAICompatibleEmbeddingModel>,
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
    ///     dict with 'embeddings' (list of lists) and 'usage' keys
    fn embed<'py>(
        &'py self,
        py: Python<'py>,
        texts: Vec<String>,
        dimensions: Option<u32>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let model = self.model.clone();

        let options = EmbeddingOptions {
            dimensions,
            user: None,
        };

        future_into_py(py, async move {
            let result = model.do_embed(texts, options).await
                .map_err(|e| AIError { message: e.to_string() })?;

            let response = serde_json::json!({
                "embeddings": result.embeddings,
                "usage": {
                    "input_tokens": result.usage.input_tokens,
                    "total_tokens": result.usage.total_tokens,
                },
            });

            serde_json::to_string(&response)
                .map_err(|e| AIError { message: e.to_string() }.into())
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

#[pyclass]
#[derive(Debug, Clone)]
struct PyImageContent {
    #[pyo3(get)]
    data: String,  // base64 encoded or URL
    #[pyo3(get)]
    media_type: String,
}

#[pymethods]
impl PyImageContent {
    #[new]
    fn new(data: &str, media_type: &str) -> Self {
        Self {
            data: data.to_string(),
            media_type: media_type.to_string(),
        }
    }
}

#[pyclass]
#[derive(Debug, Clone)]
struct PyToolCallContent {
    #[pyo3(get)]
    tool_call_id: String,
    #[pyo3(get)]
    tool_name: String,
    #[pyo3(get)]
    input: String,  // JSON string
}

#[pymethods]
impl PyToolCallContent {
    #[new]
    fn new(tool_call_id: &str, tool_name: &str, input: &str) -> Self {
        Self {
            tool_call_id: tool_call_id.to_string(),
            tool_name: tool_name.to_string(),
            input: input.to_string(),
        }
    }
}

#[pyclass]
#[derive(Debug, Clone)]
struct PyReasoningContent {
    #[pyo3(get)]
    text: String,
}

#[pymethods]
impl PyReasoningContent {
    #[new]
    fn new(text: &str) -> Self {
        Self {
            text: text.to_string(),
        }
    }
}

#[pyclass]
#[derive(Debug, Clone)]
enum PyContentPart {
    Text { text: String },
    Image { image: PyImageContent },
    Reasoning { reasoning: PyReasoningContent },
    ToolCall { tool_call: PyToolCallContent },
}

#[pyclass]
#[derive(Debug, Clone)]
struct PyMessage {
    #[pyo3(get)]
    role: String,
    #[pyo3(get)]
    content: PyMessageContent,
}

#[pyclass]
#[derive(Debug, Clone)]
enum PyMessageContent {
    Simple { text: String },
    Complex { parts: Vec<PyContentPart> },
}

#[pymethods]
impl PyMessage {
    #[new]
    fn new(role: &str, content: &Bound<'_, PyAny>) -> PyResult<Self> {
        let role_str = role.to_string();
        
        // Check if content is a string (simple message)
        if content.is_instance_of::<pyo3::types::PyString>() {
            let text = content.extract::<String>()?;
            return Ok(Self {
                role: role_str,
                content: PyMessageContent::Simple { text },
            });
        }
        
        // Check if content is a list (complex message with parts)
        if content.is_instance_of::<pyo3::types::PyList>() {
            let parts_list = content.downcast::<pyo3::types::PyList>()?;
            let mut parts = Vec::new();
            
            for part_obj in parts_list {
                let part_dict = part_obj.downcast::<pyo3::types::PyDict>()?;
                let part_type = part_dict.get_item("type")?.unwrap().extract::<String>()?;
                
                match part_type.as_str() {
                    "text" => {
                        let text = part_dict.get_item("text")?.unwrap().extract::<String>()?;
                        parts.push(PyContentPart::Text { text });
                    }
                    "image" => {
                        let image_data = part_dict.get_item("data")?.unwrap().extract::<String>()?;
                        let media_type = part_dict.get_item("media_type")?.unwrap().extract::<String>()?;
                        let image = PyImageContent::new(&image_data, &media_type);
                        parts.push(PyContentPart::Image { image });
                    }
                    "reasoning" => {
                        let text = part_dict.get_item("text")?.unwrap().extract::<String>()?;
                        let reasoning = PyReasoningContent::new(&text);
                        parts.push(PyContentPart::Reasoning { reasoning });
                    }
                    "tool_call" => {
                        let tool_call_id = part_dict.get_item("tool_call_id")?.unwrap().extract::<String>()?;
                        let tool_name = part_dict.get_item("tool_name")?.unwrap().extract::<String>()?;
                        let input = part_dict.get_item("input")?.unwrap().extract::<String>()?;
                        let tool_call = PyToolCallContent::new(&tool_call_id, &tool_name, &input);
                        parts.push(PyContentPart::ToolCall { tool_call });
                    }
                    _ => {}
                }
            }
            
            return Ok(Self {
                role: role_str,
                content: PyMessageContent::Complex { parts },
            });
        }
        
        Err(pyo3::exceptions::PyValueError::new_err(
            "Content must be a string or list of content parts"
        ))
    }
}

fn convert_messages_to_prompt(messages: Vec<PyMessage>) -> Prompt {
    let mut prompt = Prompt::new(vec![]);
    
    for msg in messages {
        match msg.role.as_str() {
            "system" => {
                let content = match &msg.content {
                    PyMessageContent::Simple { text } => text.clone(),
                    PyMessageContent::Complex { parts } => {
                        // For system messages, concatenate all text parts
                        parts.iter()
                            .filter_map(|p| match p {
                                PyContentPart::Text { text } => Some(text.clone()),
                                _ => None,
                            })
                            .collect::<Vec<_>>()
                            .join("\n")
                    }
                };
                prompt.messages.push(ai_sdk_openai_compatible::Message::system(&content));
            }
            "user" => {
                match &msg.content {
                    PyMessageContent::Simple { text } => {
                        prompt.messages.push(ai_sdk_openai_compatible::Message::user(text));
                    }
                    PyMessageContent::Complex { parts } => {
                        let mut content_parts = Vec::new();
                        
                        for part in parts {
                            match part {
                                PyContentPart::Text { text } => {
                                    content_parts.push(
                                        ai_sdk_openai_compatible::types::prompt::ContentPart::Text(
                                            ai_sdk_openai_compatible::types::prompt::TextContent {
                                                text: text.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                PyContentPart::Image { image } => {
                                    content_parts.push(
                                        ai_sdk_openai_compatible::types::prompt::ContentPart::Image(
                                            ai_sdk_openai_compatible::types::prompt::ImageContent {
                                                data: image.data.clone(),
                                                media_type: image.media_type.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                PyContentPart::Reasoning { reasoning } => {
                                    content_parts.push(
                                        ai_sdk_openai_compatible::types::prompt::ContentPart::Reasoning(
                                            ai_sdk_openai_compatible::types::prompt::ReasoningContent {
                                                text: reasoning.text.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                PyContentPart::ToolCall { tool_call } => {
                                    let input: serde_json::Value = serde_json::from_str(&tool_call.input)
                                        .unwrap_or_else(|_| serde_json::json!({}));
                                    content_parts.push(
                                        ai_sdk_openai_compatible::types::prompt::ContentPart::ToolCall(
                                            ai_sdk_openai_compatible::types::prompt::ToolCallContent {
                                                tool_call_id: tool_call.tool_call_id.clone(),
                                                tool_name: tool_call.tool_name.clone(),
                                                input,
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                            }
                        }
                        
                        prompt.messages.push(ai_sdk_openai_compatible::Message::user_with_parts(content_parts));
                    }
                }
            }
            "assistant" => {
                match &msg.content {
                    PyMessageContent::Simple { text } => {
                        prompt.messages.push(ai_sdk_openai_compatible::Message::assistant(text));
                    }
                    PyMessageContent::Complex { parts } => {
                        let mut content_parts = Vec::new();
                        
                        for part in parts {
                            match part {
                                PyContentPart::Text { text } => {
                                    content_parts.push(
                                        ai_sdk_openai_compatible::types::prompt::ContentPart::Text(
                                            ai_sdk_openai_compatible::types::prompt::TextContent {
                                                text: text.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                PyContentPart::Reasoning { reasoning } => {
                                    content_parts.push(
                                        ai_sdk_openai_compatible::types::prompt::ContentPart::Reasoning(
                                            ai_sdk_openai_compatible::types::prompt::ReasoningContent {
                                                text: reasoning.text.clone(),
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                PyContentPart::ToolCall { tool_call } => {
                                    let input: serde_json::Value = serde_json::from_str(&tool_call.input)
                                        .unwrap_or_else(|_| serde_json::json!({}));
                                    content_parts.push(
                                        ai_sdk_openai_compatible::types::prompt::ContentPart::ToolCall(
                                            ai_sdk_openai_compatible::types::prompt::ToolCallContent {
                                                tool_call_id: tool_call.tool_call_id.clone(),
                                                tool_name: tool_call.tool_name.clone(),
                                                input,
                                                provider_options: None,
                                            }
                                        )
                                    );
                                }
                                PyContentPart::Image { .. } => {
                                    // Ignore images in assistant messages
                                }
                            }
                        }
                        
                        if !content_parts.is_empty() {
                            prompt.messages.push(ai_sdk_openai_compatible::Message::assistant_with_parts(content_parts));
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
    stream: Option<std::sync::Arc<tokio::sync::Mutex<ai_sdk_openai_compatible::LanguageModelStream>>>,
}

impl AsyncGenerator {
    fn new(stream: ai_sdk_openai_compatible::LanguageModelStream) -> Self {
        Self {
            stream: Some(std::sync::Arc::new(tokio::sync::Mutex::new(stream))),
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
                    Some(Ok(ai_sdk_openai_compatible::StreamPart::TextDelta { delta })) => {
                        return Ok(serde_json::json!({"type": "text", "delta": delta}).to_string());
                    }
                    Some(Ok(ai_sdk_openai_compatible::StreamPart::ReasoningDelta { delta })) => {
                        return Ok(serde_json::json!({"type": "reasoning", "delta": delta}).to_string());
                    }
                    Some(Ok(ai_sdk_openai_compatible::StreamPart::ToolCallStart { id })) => {
                        return Ok(serde_json::json!({"type": "tool_call_start", "tool_id": id}).to_string());
                    }
                    Some(Ok(ai_sdk_openai_compatible::StreamPart::ToolCallDelta { id, name, arguments })) => {
                        return Ok(serde_json::json!({
                            "type": "tool_call_delta",
                            "tool_id": id,
                            "name": name,
                            "arguments": arguments
                        }).to_string());
                    }
                    Some(Ok(ai_sdk_openai_compatible::StreamPart::ToolCallEnd { id })) => {
                        return Ok(serde_json::json!({"type": "tool_call_end", "tool_id": id}).to_string());
                    }
                    Some(Ok(ai_sdk_openai_compatible::StreamPart::Finish { reason: _, usage })) => {
                        let mut response = serde_json::json!({"type": "finish"});
                        if let Some(usage) = usage {
                            response["usage"] = serde_json::json!({
                                "input_tokens": usage.input_tokens,
                                "output_tokens": usage.output_tokens,
                                "total_tokens": usage.total_tokens,
                            });
                        }
                        return Ok(response.to_string());
                    }
                    Some(Ok(_)) => continue, // Skip metadata, get next event
                    Some(Err(e)) => return Err(AIError { message: e.to_string() }.into()),
                    None => return Ok("[DONE]".to_string()), // End of stream marker
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
    m.add_class::<PyMessage>()?;
    m.add_class::<PyMessageContent>()?;
    m.add_class::<PyContentPart>()?;
    m.add_class::<PyImageContent>()?;
    m.add_class::<PyToolCallContent>()?;
    m.add_class::<PyReasoningContent>()?;
    m.add_class::<PyToolDefinition>()?;
    m.add_function(wrap_pyfunction!(create_chat_model_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_completion_model_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_embedding_model_py, m)?)?;
    m.add("AIError", m.py().get_type::<AIError>())?;
    
    Ok(())
}
