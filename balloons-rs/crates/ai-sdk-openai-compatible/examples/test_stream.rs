use futures::StreamExt;
use ai_sdk_openai_compatible::LanguageModel;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("Testing streaming...");
    
    let config = ai_sdk_openai_compatible::ChatConfig {
        base_url: "http://192.168.0.196:8000".to_string(),
        model_id: "Qwen3.5-122B-A10B-Q6_K-00001-of-00004.gguf".to_string(),
        api_key: None,
        headers: reqwest::header::HeaderMap::new(),
    };
    
    let model = ai_sdk_openai_compatible::OpenAICompatibleChatModel::new(config)?;
    
    let prompt = ai_sdk_openai_compatible::Prompt::with_user("run ls");
    
    let mut tools = Vec::new();
    tools.push(ai_sdk_openai_compatible::ToolDefinition {
        name: "Bash".to_string(),
        description: Some("Run bash".to_string()),
        parameters: serde_json::json!({
            "type": "object",
            "properties": {
                "command": {"type": "string"}
            },
            "required": ["command"]
        }),
        strict: None,
    });
    
    let options = ai_sdk_openai_compatible::CallOptions {
        max_tokens: Some(1000),
        temperature: Some(0.7),
        tools: Some(tools),
        tool_choice: Some(ai_sdk_openai_compatible::ToolChoice::Auto),
        ..Default::default()
    };
    
    let stream = model.do_stream(prompt, options).await?;
    tokio::pin!(stream);
    
    let mut event_count = 0;
    while let Some(result) = stream.next().await {
        match result {
            Ok(part) => {
                event_count += 1;
                println!("Event {}: {:?}", event_count, part);
            }
            Err(e) => {
                println!("Error: {:?}", e);
                break;
            }
        }
    }
    
    println!("Total events: {}", event_count);
    Ok(())
}
