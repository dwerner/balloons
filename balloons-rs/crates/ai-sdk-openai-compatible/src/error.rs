//! Error types for the OpenAI-compatible provider.

use thiserror::Error;

#[derive(Error, Debug)]
pub enum Error {
    #[error("API call failed: {0}")]
    ApiCall(#[from] ApiCallError),

    #[error("Invalid response: {0}")]
    InvalidResponse(String),

    #[error("Invalid JSON: {0}")]
    InvalidJson(#[from] serde_json::Error),

    #[error("Invalid schema: {0}")]
    InvalidSchema(String),

    #[error("Streaming error: {0}")]
    StreamingError(String),

    #[error("Tool error: {0}")]
    ToolError(String),

    #[error("Configuration error: {0}")]
    ConfigurationError(String),

    #[error("Unknown error: {0}")]
    Unknown(String),
}

#[derive(Error, Debug)]
pub enum ApiCallError {
    #[error("HTTP error: {0}")]
    Http(reqwest::Error),

    #[error("Network error: {0}")]
    Network(String),

    #[error("Timeout: {0}")]
    Timeout(String),

    #[error("Authentication failed: {0}")]
    Authentication(String),
}

impl From<reqwest::Error> for ApiCallError {
    fn from(err: reqwest::Error) -> Self {
        if err.is_timeout() {
            ApiCallError::Timeout(err.to_string())
        } else if err.is_connect() {
            ApiCallError::Network(err.to_string())
        } else {
            ApiCallError::Http(err)
        }
    }
}
