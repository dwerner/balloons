//! Image generation model (stub - not yet implemented).

/// Configuration for image model.
#[derive(Debug, Clone)]
pub struct ImageConfig {
    pub base_url: String,
    pub model_id: String,
    pub api_key: Option<String>,
}

/// OpenAI-compatible image model.
pub struct OpenAICompatibleImageModel {
    #[allow(dead_code)]
    config: ImageConfig,
}

impl OpenAICompatibleImageModel {
    pub fn new(config: ImageConfig) -> Result<Self, crate::Error> {
        Ok(Self { config })
    }
}
