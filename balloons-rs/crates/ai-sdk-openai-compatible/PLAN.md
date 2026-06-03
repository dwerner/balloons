# Port Plan: @ai-sdk/openai-compatible to Rust

## Goal
Port the OpenAI-compatible provider from TypeScript to Rust for local model support in Balloons.

## Scope
- **Source**: ~2.9K lines TypeScript (@ai-sdk/openai-compatible)
- **Target**: Single crate with modules
- **API**: Async-first (tokio-based)

## Crate Structure (Single Crate)
```
crates/ai-sdk-openai-compatible/
├── Cargo.toml
└── src/
    ├── lib.rs
    ├── provider.rs          # Provider factory
    ├── error.rs             # Error types
    ├── types/               # Core types
    │   ├── mod.rs
    │   ├── prompt.rs        # System/User/Assistant/Tool messages + ContentPart
    │   ├── tool.rs          # Tool definitions, ToolChoice, ToolCall
    │   ├── usage.rs         # Token usage tracking
    │   └── finish_reason.rs
    ├── http/                # HTTP abstraction
    │   ├── mod.rs
    │   ├── client.rs        # reqwest-based async client
    │   └── response.rs      # Response handling
    ├── streaming/           # Streaming utilities
    │   ├── mod.rs
    │   ├── sse.rs           # SSE parser (async-stream)
    │   └── json_stream.rs   # JSON stream parser
    ├── chat/                # Chat completion
    │   ├── mod.rs
    │   ├── model.rs         # OpenAICompatibleChatModel
    │   ├── messages.rs      # Prompt conversion
    │   ├── tools.rs         # Tool preparation/parsing
    │   └── types.rs         # API request/response schemas
    ├── completion/          # Text completion (stub)
    │   ├── mod.rs
    │   └── model.rs
    ├── embedding/           # Embeddings (stub)
    │   ├── mod.rs
    │   └── model.rs
    └── image/               # Image generation (stub)
        └── model.rs
```

## Key Design Decisions

### Async API
```rust
#[async_trait]
pub trait LanguageModel {
    fn provider(&self) -> &str;
    fn model_id(&self) -> &str;
    async fn do_generate(&self, prompt: Prompt, options: CallOptions) -> Result<GenerateResult, Error>;
    async fn do_stream(&self, prompt: Prompt, options: CallOptions) -> Result<LanguageModelStream, Error>;
}
```

### Dependencies
- `reqwest` - HTTP client
- `tokio` - Async runtime
- `serde` + `serde_json` - JSON serialization
- `schemars` - JSON schema validation
- `thiserror` - Error types
- `async-trait` - Async trait support
- `async-stream` - Async streaming
- `futures` - Stream utilities
- `uuid` - ID generation

## Implementation Status

### Phase 1: Core Types ✅
- [x] Define `LanguageModel` trait with `do_generate`/`do_stream`
- [x] Prompt/content/tool types (System/User/Assistant/Tool messages)
- [x] ContentPart enum (Text, Image, File, Reasoning, ToolCall)
- [x] Tool types (ToolDefinition, ToolChoice, ToolCall)
- [x] Usage tracking
- [x] Finish reasons
- [x] Error types

### Phase 2: HTTP & Streaming ✅
- [x] Async HTTP client wrapper (reqwest-based)
- [x] JSON request/response handling
- [x] SSE streaming parser (async-stream based)
- [x] JSON stream parser

### Phase 3: Chat Model ✅
- [x] API types (OpenAI-compatible schemas)
- [x] Message conversion (prompt → OpenAI format)
- [x] Tool call handling
- [x] `do_generate` (non-streaming)
- [x] `do_stream` (streaming)

### Phase 4: Additional Models (Stubs)
- [x] Completion model (stub)
- [x] Embedding model (stub)
- [x] Image model (stub)

### Phase 5: Integration ✅
- [x] Provider factory function (`create_chat_model`)
- [x] Basic structure compiles

## Current Status
✅ **Core implementation complete** - Chat model with streaming support
✅ **Tests passing** - 8 integration tests with wiremock
✅ **Real server tests passing** - 3 tests against 192.168.0.196:8000
✅ **Completion model implemented** - do_generate + do_stream with 4 tests
✅ **Embedding model implemented** - do_embed with 4 tests
⚠️ **Image model stub** - Ready to implement

## Tests
- ✅ Simple chat completion
- ✅ Chat completion with system prompt
- ✅ Chat completion with tool calls
- ✅ Streaming chat completion
- ✅ Streaming with tool calls
- ✅ Error handling

## Usage Example

```rust
use ai_sdk_openai_compatible::{create_chat_model, CallOptions, LanguageModel, Prompt, ProviderConfig};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Create provider for local model
    let config = ProviderConfig::new("http://localhost:8080");
    let model = create_chat_model(config, "qwen3.5")?;

    // Simple chat
    let prompt = Prompt::with_user("Hello, how are you?");
    let result = model.do_generate(prompt, CallOptions::default()).await?;
    println!("{}", result.text.unwrap());

    // Streaming
    let prompt = Prompt::with_user("Tell me a story");
    let stream = model.do_stream(prompt, CallOptions::default()).await?;
    
    use futures::StreamExt;
    tokio::pin!(stream);
    while let Some(part) = stream.next().await {
        match part? {
            ai_sdk_openai_compatible::StreamPart::TextDelta { delta } => {
                print!("{}", delta);
            }
            _ => {}
        }
    }

    Ok(())
}
```

## Next Steps
1. Test against real local models (llama.cpp, Ollama)
2. Implement completion model
3. Implement embedding model
4. Add Python bindings (pyo3) if needed
5. Add more comprehensive tests
6. Documentation
