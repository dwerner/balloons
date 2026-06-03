//! OpenAI-compatible embedding model.

use crate::embedding::types::{EmbeddingRequest, EmbeddingResponse};
use crate::error::Error;
use crate::http::HttpClient;
use crate::types::Usage;
use reqwest::header::HeaderMap;

/// Configuration for the embedding model.
#[derive(Debug, Clone)]
pub struct EmbeddingConfig {
    pub base_url: String,
    pub model_id: String,
    pub api_key: Option<String>,
    pub headers: HeaderMap,
}

/// OpenAI-compatible embedding model.
pub struct OpenAICompatibleEmbeddingModel {
    config: EmbeddingConfig,
    client: HttpClient,
}

/// Result from embedding call.
#[derive(Debug, Clone)]
pub struct EmbeddingResult {
    pub embeddings: Vec<Vec<f32>>,
    pub usage: Usage,
}

/// Options for embedding calls.
#[derive(Debug, Clone, Default)]
pub struct EmbeddingOptions {
    /// Number of dimensions for the output embeddings.
    pub dimensions: Option<u32>,
    /// User identifier for abuse monitoring.
    pub user: Option<String>,
}

impl OpenAICompatibleEmbeddingModel {
    pub fn new(config: EmbeddingConfig) -> Result<Self, Error> {
        let mut client = HttpClient::new(&config.base_url)?;

        if let Some(ref api_key) = config.api_key {
            client = client.with_api_key(api_key);
        }

        if !config.headers.is_empty() {
            client = client.with_headers(config.headers.clone());
        }

        Ok(Self {
            config,
            client,
        })
    }

    /// Create embeddings for the given text values.
    pub async fn do_embed(
        &self,
        values: Vec<String>,
        options: EmbeddingOptions,
    ) -> Result<EmbeddingResult, Error> {
        let request = EmbeddingRequest {
            model: self.config.model_id.clone(),
            input: values,
            encoding_format: Some("float".to_string()),
            dimensions: options.dimensions,
            user: options.user,
        };

        let response: EmbeddingResponse = self
            .client
            .post_json("/v1/embeddings", &request)
            .await?;

        let embeddings = response.data
            .into_iter()
            .map(|d| d.embedding)
            .collect();

        let usage = response.usage.map(|u| Usage {
            input_tokens: u.prompt_tokens,
            output_tokens: 0,
            total_tokens: u.total_tokens,
        }).unwrap_or_default();

        Ok(EmbeddingResult {
            embeddings,
            usage,
        })
    }
}

// Note: Embedding models don't implement LanguageModel trait
// They have their own do_embed method instead
