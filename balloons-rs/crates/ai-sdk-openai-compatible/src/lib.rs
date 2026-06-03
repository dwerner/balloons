//! AI SDK OpenAI-Compatible Provider
//!
//! A Rust implementation of the OpenAI-compatible provider for local model support.

pub mod chat;
pub mod completion;
pub mod embedding;
pub mod error;
pub mod http;
pub mod image;
pub mod provider;
pub mod streaming;
pub mod types;

pub use error::Error;
pub use provider::{
    create_chat_model, create_completion_model, create_embedding_model, ProviderConfig,
};
pub use types::*;

// Re-export chat model types
pub use chat::{ChatConfig, OpenAICompatibleChatModel};

// Re-export completion model types
pub use completion::{CompletionConfig, OpenAICompatibleCompletionModel};

// Re-export embedding types
pub use embedding::{EmbeddingConfig, EmbeddingOptions, EmbeddingResult, OpenAICompatibleEmbeddingModel};
