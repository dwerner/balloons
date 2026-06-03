//! Token usage tracking.

use serde::{Deserialize, Serialize};

/// Token usage statistics.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Usage {
    pub input_tokens: u32,
    pub output_tokens: u32,
    pub total_tokens: u32,
}

impl Usage {
    pub fn new(input_tokens: u32, output_tokens: u32) -> Self {
        let total_tokens = input_tokens + output_tokens;
        Self {
            input_tokens,
            output_tokens,
            total_tokens,
        }
    }
}
