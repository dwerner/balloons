use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct FunctionCallDelta {
    name: Option<String>,
    arguments: Option<String>,
}

fn main() {
    let json = r#"{"arguments":"\"command\":\""}"#;
    let func: FunctionCallDelta = serde_json::from_str(json).unwrap();
    println!("Parsed: {:?}", func);
    println!("Arguments: {:?}", func.arguments);
}
