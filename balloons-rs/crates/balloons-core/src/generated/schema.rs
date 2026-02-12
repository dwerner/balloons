//! AUTO-GENERATED CODE - DO NOT EDIT
//!
//! Generated from Python domain entities marked with @rust_schema.
//! Source: models.py and other domain modules
//! Generated: 2026-02-12T12:22:32.313702
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
    #[serde(default)]
    pub exchange_id: Option<String>,
    #[serde(default)]
    pub sentiment: Option<String>,
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
    pub children: Vec<serde_json::Value>,
    pub returned: bool,
    pub return_condition: String,
    #[serde(default)]
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
    pub spec_version: String,
    #[serde(default)]
    pub session_duration_minutes: Option<i64>,
    pub turn_count: i64,
    pub sentiment_counts: serde_json::Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GoalData {
    pub id: String,
    pub title: String,
    pub description: String,
    pub weight: i64,
    pub status: String,
    #[serde(default)]
    pub acceptance_criteria: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
    #[serde(default)]
    pub completed_at: Option<String>,
    #[serde(default)]
    pub supersedes_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanData {
    pub id: String,
    pub goal_id: String,
    pub title: String,
    pub description: String,
    pub status: String,
    pub created_at: String,
    pub updated_at: String,
    #[serde(default)]
    pub completed_at: Option<String>,
    #[serde(default)]
    pub postmortem: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TodoData {
    pub id: String,
    pub title: String,
    pub description: String,
    pub status: String,
    pub is_spike: bool,
    pub created_at: String,
    pub updated_at: String,
    #[serde(default)]
    pub completed_at: Option<String>,
    #[serde(default)]
    pub timebox_minutes: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TodoPlanLink {
    pub todo_id: String,
    pub plan_id: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TodoDependency {
    pub todo_id: String,
    pub depends_on_id: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionBinding {
    pub id: String,
    pub session_id: String,
    pub entity_type: String,
    pub entity_id: String,
    pub role: String,
    pub created_at: String,
    #[serde(default)]
    pub released_at: Option<String>,
}
