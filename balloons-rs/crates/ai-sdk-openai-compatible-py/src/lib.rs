//! Python bindings for ai-sdk-openai-compatible.
//!
//! Provides async Python access to OpenAI-compatible LLM APIs.

use pyo3::prelude::*;
use pyo3_async_runtimes::tokio::future_into_py;
use futures::TryFutureExt;

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
    ///
    /// Returns:
    ///     dict with 'text', 'usage', and 'finish_reason' keys
   fn generate<'py>(
        &'py self,
        py: Python<'py>,
        messages: Vec<PyMessage>,
        max_tokens: Option<u32>,
        temperature: Option<f32>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let model = self.model.clone();
        let prompt = convert_messages_to_prompt(messages);

        let options = CallOptions {
            max_tokens,
            temperature: Some(temperature.unwrap_or(0.7)),
            ..Default::default()
        };

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
    ///
    /// Returns:
    ///     Async generator yielding text deltas
    fn stream<'py>(
        &'py self,
        py: Python<'py>,
        messages: Vec<PyMessage>,
        max_tokens: Option<u32>,
        temperature: Option<f32>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let model = self.model.clone();
        let prompt = convert_messages_to_prompt(messages);

        let options = CallOptions {
            max_tokens,
            temperature: Some(temperature.unwrap_or(0.7)),
            ..Default::default()
        };

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
#[derive(Debug)]
struct PyMessage {
    #[pyo3(get)]
    role: String,
    #[pyo3(get)]
    content: String,
}

impl<'a, 'py> FromPyObject<'a, 'py> for PyMessage {
    type Error = PyErr;
    
    fn extract(obj: pyo3::Borrowed<'a, 'py, pyo3::PyAny>) -> Result<Self, Self::Error> {
        let role = obj.getattr("role")?.extract()?;
        let content = obj.getattr("content")?.extract()?;
        Ok(PyMessage { role, content })
    }
}

#[pymethods]
impl PyMessage {
    #[new]
    fn new(role: &str, content: &str) -> Self {
        Self {
            role: role.to_string(),
            content: content.to_string(),
        }
    }
}

fn convert_messages_to_prompt(messages: Vec<PyMessage>) -> Prompt {
    let mut prompt = Prompt::new(vec![]);
    
    for msg in messages {
        match msg.role.as_str() {
            "system" => {
                prompt.messages.push(ai_sdk_openai_compatible::Message::system(&msg.content));
            }
            "user" => {
                prompt.messages.push(ai_sdk_openai_compatible::Message::user(&msg.content));
            }
            "assistant" => {
                prompt.messages.push(ai_sdk_openai_compatible::Message::assistant(&msg.content));
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
            
            let mut stream_guard = stream.lock().await;
            match stream_guard.next().await {
                Some(Ok(ai_sdk_openai_compatible::StreamPart::TextDelta { delta })) => {
                    Ok(serde_json::json!({"type": "text", "delta": delta}).to_string())
                }
                Some(Ok(ai_sdk_openai_compatible::StreamPart::ReasoningDelta { delta })) => {
                    Ok(serde_json::json!({"type": "reasoning", "delta": delta}).to_string())
                }
                Some(Ok(ai_sdk_openai_compatible::StreamPart::Finish { .. })) => {
                    Ok("[DONE]".to_string())
                }
                Some(Ok(_)) => Ok(String::new()), // Skip tool calls for now
                Some(Err(e)) => Err(AIError { message: e.to_string() }.into()),
                None => Ok(String::new()),
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
    m.add_function(wrap_pyfunction!(create_chat_model_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_completion_model_py, m)?)?;
    m.add_function(wrap_pyfunction!(create_embedding_model_py, m)?)?;
    m.add("AIError", m.py().get_type::<AIError>())?;
    
    Ok(())
}
