//! AUTO-GENERATED CODE - DO NOT EDIT
//!
//! Generated from Python domain entities marked with @rust_schema.
//! Source: models.py and other domain modules
//! Generated: 2026-02-08T11:03:46.731877
//!
//! To regenerate:
//!     python -m codegen.generate_rust
//!
//! To add new types, add @rust_schema decorator to dataclasses in your domain modules.

use serde::{Deserialize, Serialize};


#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnData {
    pub id: String,
    pub role: String,
    pub content_block: serde_json::Value,
    pub tokens: i64,
    pub timestamp: String,
    pub context_mode: String,
    pub summary: String,
    pub exchange_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionData {
    pub id: String,
    pub created: String,
    pub last_modified: String,
    pub model: String,
    pub turns: Vec<TurnData>,
    pub total_input_tokens: i64,
    pub total_output_tokens: i64,
    pub total_cost: f64,
    pub context_window: i64,
    pub parent_id: Option<String>,
    pub children: Vec<serde_json::Value>,
    pub returned: bool,
    pub return_condition: String,
    pub working_directories: Vec<String>,
    pub title: String,
    pub summary: String,
    pub fork_name: String,
    pub fork_status: String,
    pub fork_point_turn: i64,
    pub merge_point_turn: i64,
    pub merge_message: String,
    pub backend_name: String,
    pub cached_context_tokens: i64,
    pub message_queue: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMetadata {
    pub id: String,
    pub name: String,
    pub created_at: i64,
    pub updated_at: i64,
    pub turn_count: i64,
}
