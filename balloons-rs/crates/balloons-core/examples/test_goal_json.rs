use balloons_core::GoalData;

fn main() {
    let goal = GoalData {
        id: "test".to_string(),
        title: "Test".to_string(),
        description: "Test".to_string(),
        weight: 5,
        status: "active".to_string(),
        acceptance_criteria: vec!["Done".to_string()],
        created_at: "2026-01-01T00:00:00".to_string(),
        updated_at: "2026-01-01T00:00:00".to_string(),
        completed_at: None,
        supersedes_id: None,
        parent_goal_id: Some("parent-123".to_string()),
    };

    let json = serde_json::to_string(&goal).unwrap();
    println!("Serialized JSON: {}", json);
    
    // Also test with None
    let goal2 = GoalData {
        id: "test2".to_string(),
        title: "Test2".to_string(),
        description: "Test2".to_string(),
        weight: 5,
        status: "active".to_string(),
        acceptance_criteria: vec!["Done".to_string()],
        created_at: "2026-01-01T00:00:00".to_string(),
        updated_at: "2026-01-01T00:00:00".to_string(),
        completed_at: None,
        supersedes_id: None,
        parent_goal_id: None,
    };
    
    let json2 = serde_json::to_string(&goal2).unwrap();
    println!("Serialized JSON (None): {}", json2);
}
