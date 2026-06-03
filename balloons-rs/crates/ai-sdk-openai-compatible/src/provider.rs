//! Provider factory for creating OpenAI-compatible models.

use crate::chat::{ChatConfig, OpenAICompatibleChatModel};
use crate::completion::{CompletionConfig, OpenAICompatibleCompletionModel};
use crate::embedding::{EmbeddingConfig, OpenAICompatibleEmbeddingModel};
use crate::error::Error;
use reqwest::header::HeaderMap;

/// Configuration for the OpenAI-compatible provider.
#[derive(Debug, Clone)]
pub struct ProviderConfig {
    pub base_url: String,
    pub api_key: Option<String>,
    pub headers: HeaderMap,
}

impl ProviderConfig {
    pub fn new(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            api_key: None,
            headers: HeaderMap::new(),
        }
    }

    pub fn with_api_key(mut self, api_key: impl Into<String>) -> Self {
        self.api_key = Some(api_key.into());
        self
    }

    pub fn with_header(mut self, key: &str, value: &str) -> Result<Self, Error> {
        let header_name: reqwest::header::HeaderName = key.parse().map_err(|e| {
            Error::ConfigurationError(format!("Invalid header name: {}", e))
        })?;
        let header_value: reqwest::header::HeaderValue = value.parse().map_err(|e| {
            Error::ConfigurationError(format!("Invalid header value: {}", e))
        })?;
        self.headers.insert(header_name, header_value);
        Ok(self)
    }
}

/// Create a chat model from the provider.
pub fn create_chat_model(
    config: ProviderConfig,
    model_id: impl Into<String>,
) -> Result<OpenAICompatibleChatModel, Error> {
    let chat_config = ChatConfig {
        base_url: config.base_url,
        model_id: model_id.into(),
        api_key: config.api_key,
        headers: config.headers,
    };

    OpenAICompatibleChatModel::new(chat_config)
}

/// Create a completion model from the provider.
pub fn create_completion_model(
    config: ProviderConfig,
    model_id: impl Into<String>,
) -> Result<OpenAICompatibleCompletionModel, Error> {
    let completion_config = CompletionConfig {
        base_url: config.base_url,
        model_id: model_id.into(),
        api_key: config.api_key,
        headers: config.headers,
    };

    OpenAICompatibleCompletionModel::new(completion_config)
}

/// Create an embedding model from the provider.
pub fn create_embedding_model(
    config: ProviderConfig,
    model_id: impl Into<String>,
) -> Result<OpenAICompatibleEmbeddingModel, Error> {
    let embedding_config = EmbeddingConfig {
        base_url: config.base_url,
        model_id: model_id.into(),
        api_key: config.api_key,
        headers: config.headers,
    };

    OpenAICompatibleEmbeddingModel::new(embedding_config)
}
