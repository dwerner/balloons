//! AUTO-GENERATED CODE - DO NOT EDIT
//!
//! Generated from Python domain entities marked with @rust_schema.
//! Source: models.py and other domain modules
//! Generated: 2026-05-29T13:07:50.519899
//!
//! To regenerate:
//!     python -m codegen.generate_rust
//!
//! To add new types, add @rust_schema decorator to dataclasses in your domain modules.

use serde::{Deserialize, Serialize};


#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ForkChildData {
    pub session_id: String,
    pub name: String,
    pub status: String,
    pub fork_point: i64,
    #[serde(default)]
    pub merge_point: i64,
    #[serde(default)]
    pub return_condition: String,
    #[serde(default)]
    pub prompt: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnData {
    pub id: String,
    pub role: String,
    pub content_block: serde_json::Value,
    pub tokens: i64,
    pub timestamp: String,
    pub context_mode: String,
    pub summary: String,
    #[serde(default)]
    pub exchange_id: Option<String>,
    #[serde(default)]
    pub sentiment: Option<String>,
    #[serde(default)]
    pub started_at: Option<String>,
    #[serde(default)]
    pub ended_at: Option<String>,
    #[serde(default)]
    pub parallel_group_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionData {
    pub id: String,
    pub created: String,
    pub last_modified: String,
    pub model: String,
    pub total_input_tokens: i64,
    pub total_output_tokens: i64,
    pub total_cost: f64,
    pub context_window: i64,
    #[serde(default)]
    pub parent_id: Option<String>,
    #[serde(default)]
    pub children: Vec<ForkChildData>,
    #[serde(default)]
    pub returned: bool,
    #[serde(default)]
    pub return_condition: String,
    #[serde(default)]
    pub working_directories: Vec<String>,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub summary: String,
    #[serde(default)]
    pub fork_name: String,
    #[serde(default)]
    pub fork_status: String,
    #[serde(default)]
    pub fork_point_turn: i64,
    #[serde(default)]
    pub merge_point_turn: i64,
    #[serde(default)]
    pub merge_message: String,
    #[serde(default)]
    pub backend_name: String,
    #[serde(default)]
    pub cached_context_tokens: i64,
    #[serde(default)]
    pub prompt_files: Vec<String>,
    #[serde(default)]
    pub enabled_tools: Vec<String>,
    #[serde(default)]
    pub concluded: bool,
    #[serde(default)]
    pub concluded_at: Option<String>,
    #[serde(default)]
    pub concluded_reason: String,
    #[serde(default)]
    pub message_queue: serde_json::Value,
    #[serde(default)]
    pub loaded_domains: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnOrder {
    pub session_id: String,
    #[serde(default)]
    pub turn_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMetadata {
    pub id: String,
    pub name: String,
    pub created_at: i64,
    pub updated_at: i64,
    pub turn_count: i64,
    #[serde(default)]
    pub cached_context_tokens: i64,
    #[serde(default)]
    pub context_window: i64,
    #[serde(default)]
    pub working_directories: Vec<String>,
    #[serde(default)]
    pub parent_id: Option<String>,
    #[serde(default)]
    pub fork_name: String,
    #[serde(default)]
    pub fork_status: String,
    #[serde(default)]
    pub children: Vec<ForkChildData>,
    #[serde(default)]
    pub loaded_domains: Vec<String>,
    #[serde(default)]
    pub backend_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReviewData {
    pub id: String,
    pub session_id: String,
    pub reviewed_at: String,
    pub model_under_review: String,
    pub review_backend: String,
    pub score_correctness: i64,
    pub score_efficiency: i64,
    pub score_instruction_following: i64,
    pub score_recovery: i64,
    pub score_autonomy: i64,
    pub score_judgment: i64,
    pub score_communication: i64,
    pub task_category: String,
    pub task_description: String,
    pub user_summary: String,
    pub llm_commentary: String,
    #[serde(default)]
    pub spec_version: String,
    #[serde(default)]
    pub session_duration_minutes: Option<i64>,
    #[serde(default)]
    pub turn_count: i64,
    #[serde(default)]
    pub sentiment_counts: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WatcherRelation {
    pub id: String,
    pub watcher_session_id: String,
    pub target_session_id: String,
    pub target_session_name: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserData {
    pub id: String,
    pub username: String,
    pub password_hash: String,
    pub role: String,
    pub created_at: String,
    #[serde(default)]
    pub created_by: Option<String>,
    #[serde(default)]
    pub last_login: Option<String>,
    #[serde(default)]
    pub disabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserPrefs {
    #[serde(default)]
    pub pinned_session_ids: Vec<String>,
}
