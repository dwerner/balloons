# AI SDK OpenAI-Compatible

A Rust implementation of the OpenAI-compatible provider for local model support in Balloons.

## Features

- ✅ Async-first API with Tokio
- ✅ Chat completion with streaming
- ✅ Tool calling support
- ✅ System/User/Assistant/Tool message types
- ✅ OpenAI-compatible API format
- ✅ Works with any OpenAI-compatible endpoint (llama.cpp, Ollama, vLLM, etc.)

## Installation

Add to your `Cargo.toml`:

```toml
[dependencies]
ai-sdk-openai-compatible = { path = "crates/ai-sdk-openai-compatible" }
tokio = { version = "1", features = ["full"] }
futures = "0.3"
```

## Quick Start

### Simple Chat Completion

```rust
use ai_sdk_openai_compatible::{create_chat_model, CallOptions, LanguageModel, Prompt, ProviderConfig};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Create provider for local model
    let config = ProviderConfig::new("http://localhost:8080");
    let model = create_chat_model(config, "qwen3.5")?;

    // Create prompt
    let prompt = Prompt::with_user("Hello, how are you?");
    
    // Generate response
    let result = model.do_generate(prompt, CallOptions::default()).await?;
    println!("{}", result.text.unwrap());

    Ok(())
}
```

### With System Prompt

```rust
let mut prompt = Prompt::with_system("You are a helpful assistant.");
prompt.messages.push(Message::user("What is Rust?"));

let result = model.do_generate(prompt, CallOptions::default()).await?;
println!("{}", result.text.unwrap());
```

### Streaming Response

```rust
use futures::StreamExt;

let prompt = Prompt::with_user("Tell me a story");
let stream = model.do_stream(prompt, CallOptions::default()).await?;

tokio::pin!(stream);
while let Some(part) = stream.next().await {
    match part? {
        StreamPart::TextDelta { delta } => {
            print!("{}", delta);
        }
        StreamPart::Finish { reason, .. } => {
            println!("\nFinished: {:?}", reason);
        }
        _ => {}
    }
}
```

### Tool Calling

```rust
let tools = vec![ToolDefinition {
    name: "get_weather".to_string(),
    description: Some("Get weather for a location".to_string()),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name"
            }
        },
        "required": ["location"]
    }),
    strict: None,
}];

let options = CallOptions {
    tools: Some(tools),
    tool_choice: Some(ToolChoice::Auto),
    ..Default::default()
};

let result = model.do_generate(prompt, options).await?;

for tool_call in &result.tool_calls {
    println!("Calling {} with {:?}", tool_call.tool_name, tool_call.input);
}
```

## Supported Providers

This crate works with any OpenAI-compatible endpoint:

- **llama.cpp** (`http://localhost:8080`)
- **Ollama** (`http://localhost:11434`)
- **vLLM** (`http://localhost:8000`)
- **OpenRouter** (`https://openrouter.ai/api/v1`)
- **Local LLM servers**

## API Reference

### Core Types

- `LanguageModel` - Trait for language model operations
- `Prompt` - Collection of messages
- `Message` - System/User/Assistant/Tool messages
- `CallOptions` - Generation parameters
- `GenerateResult` - Non-streaming response
- `StreamPart` - Streaming response parts

### Provider Configuration

```rust
let config = ProviderConfig::new("http://localhost:8080")
    .with_api_key("your-api-key")?  // Optional
    .with_header("X-Custom-Header", "value")?;  // Optional
```

## Testing

Run tests with wiremock:

```bash
cargo test
```

## License

Proprietary - Part of the Balloons project
