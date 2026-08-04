use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct ChatCompletionChunk {
    choices: Vec<ChunkChoice>,
}

#[derive(Debug, Deserialize)]
struct ChunkChoice {
    index: u32,
    delta: ChoiceDelta,
}

#[derive(Debug, Deserialize)]
struct ChoiceDelta {
    tool_calls: Option<Vec<ToolCallDelta>>,
    content: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ToolCallDelta {
    index: u32,
    function: Option<FunctionCallDelta>,
}

#[derive(Debug, Deserialize)]
struct FunctionCallDelta {
    arguments: Option<String>,
}

fn main() {
    let json = r#"{"choices":[{"finish_reason":null,"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"command\":\""}}]}}],"created":1780615808,"id":"test","model":"test","system_fingerprint":"test","object":"chat.completion.chunk"}"#;
    let chunk: ChatCompletionChunk = serde_json::from_str(json).unwrap();
    println!("Parsed: {:?}", chunk);
    if let Some(choice) = chunk.choices.get(0) {
        println!("tool_calls: {:?}", choice.delta.tool_calls);
        if let Some(calls) = &choice.delta.tool_calls {
            for call in calls {
                println!("  call.function: {:?}", call.function);
                if let Some(func) = &call.function {
                    println!("  call.function.arguments: {:?}", func.arguments);
                }
            }
        }
    }
}
