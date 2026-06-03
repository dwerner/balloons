//! Chat completion tests.

use ai_sdk_openai_compatible::{
    create_chat_model, CallOptions, LanguageModel, Message, Prompt, ProviderConfig,
};
use wiremock::{
    matchers::{method, path},
    Mock, MockServer, ResponseTemplate,
};

#[tokio::test]
async fn test_simple_chat_completion() {
    // Start mock server
    let mock_server = MockServer::start().await;

    // Mock response
    let response_body = serde_json::json!({
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello! How can I help you?"
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 9,
            "completion_tokens": 12,
            "total_tokens": 21
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
        .mount(&mock_server)
        .await;

    // Create model
    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_chat_model(config, "test-model").unwrap();

    // Make request
    let prompt = Prompt::with_user("Hello");
    let options = CallOptions::default();
    let result = model.do_generate(prompt, options).await.unwrap();

    // Verify
    assert_eq!(result.response_id, "chatcmpl-123");
    assert_eq!(result.text, Some("Hello! How can I help you?".to_string()));
    assert_eq!(result.usage.input_tokens, 9);
    assert_eq!(result.usage.output_tokens, 12);
}

#[tokio::test]
async fn test_chat_completion_with_system_prompt() {
    let mock_server = MockServer::start().await;

    let response_body = serde_json::json!({
        "id": "chatcmpl-456",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "I am a helpful assistant."
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 8,
            "total_tokens": 23
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_chat_model(config, "test-model").unwrap();

    let mut prompt = Prompt::with_system("You are a helpful assistant.");
    prompt.messages.push(Message::user("Introduce yourself"));
    
    let options = CallOptions::default();
    let result = model.do_generate(prompt, options).await.unwrap();

    assert_eq!(result.text, Some("I am a helpful assistant.".to_string()));
}

#[tokio::test]
async fn test_chat_completion_with_tools() {
    let mock_server = MockServer::start().await;

    let response_body = serde_json::json!({
        "id": "chatcmpl-789",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "test-model",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": null,
                "tool_calls": [{
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": "{\"location\":\"San Francisco\"}"
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 15,
            "total_tokens": 35
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_chat_model(config, "test-model").unwrap();

    let prompt = Prompt::with_user("What's the weather in San Francisco?");
    
    let tools = vec![ai_sdk_openai_compatible::ToolDefinition {
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
        tool_choice: Some(ai_sdk_openai_compatible::ToolChoice::Auto),
        ..Default::default()
    };

    let result = model.do_generate(prompt, options).await.unwrap();

    assert_eq!(result.tool_calls.len(), 1);
    assert_eq!(result.tool_calls[0].tool_name, "get_weather");
    assert_eq!(result.tool_calls[0].input["location"], "San Francisco");
    assert_eq!(result.finish_reason, ai_sdk_openai_compatible::FinishReason::ToolCalls);
}

#[tokio::test]
async fn test_streaming_chat_completion() {
    let mock_server = MockServer::start().await;

    let chunks = vec![
        "data: {\"id\":\"chatcmpl-stream\",\"object\":\"chat.completion.chunk\",\"created\":1677652288,\"model\":\"test-model\",\"choices\":[{\"index\":0,\"delta\":{\"role\":\"assistant\",\"content\":\"\"},\"finish_reason\":null}]}\n\n",
        "data: {\"id\":\"chatcmpl-stream\",\"object\":\"chat.completion.chunk\",\"created\":1677652288,\"model\":\"test-model\",\"choices\":[{\"index\":0,\"delta\":{\"content\":\"Hello\"},\"finish_reason\":null}]}\n\n",
        "data: {\"id\":\"chatcmpl-stream\",\"object\":\"chat.completion.chunk\",\"created\":1677652288,\"model\":\"test-model\",\"choices\":[{\"index\":0,\"delta\":{\"content\":\"!\"},\"finish_reason\":null}]}\n\n",
        "data: {\"id\":\"chatcmpl-stream\",\"object\":\"chat.completion.chunk\",\"created\":1677652288,\"model\":\"test-model\",\"choices\":[{\"index\":0,\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n",
        "data: [DONE]\n\n",
    ];

    let combined: String = chunks.concat();

    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_string(combined)
                .append_header("Content-Type", "text/event-stream")
        )
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_chat_model(config, "test-model").unwrap();

    let prompt = Prompt::with_user("Say hello");
    let options = CallOptions::default();
    
    let stream = model.do_stream(prompt, options).await.unwrap();
    
    let mut collected_text = String::new();
    let mut finish_reason = None;
    
    use futures::StreamExt;
    let mut stream = stream;
    
    while let Some(part) = stream.next().await {
        match part.unwrap() {
            ai_sdk_openai_compatible::StreamPart::TextDelta { delta } => {
                collected_text.push_str(&delta);
            }
            ai_sdk_openai_compatible::StreamPart::Finish { reason, .. } => {
                finish_reason = Some(reason);
            }
            _ => {}
        }
    }

    assert_eq!(collected_text, "Hello!");
    assert_eq!(finish_reason, Some(ai_sdk_openai_compatible::FinishReason::Stop));
}

#[tokio::test]
async fn test_streaming_with_tool_calls() {
    let mock_server = MockServer::start().await;

    let chunks = vec![
        "data: {\"id\":\"chatcmpl-tool\",\"object\":\"chat.completion.chunk\",\"created\":1677652288,\"model\":\"test-model\",\"choices\":[{\"index\":0,\"delta\":{\"role\":\"assistant\",\"content\":null,\"tool_calls\":[{\"index\":0,\"id\":\"call_xyz\",\"type\":\"function\",\"function\":{\"name\":\"get_weather\"}}]},\"finish_reason\":null}]}\n\n",
        "data: {\"id\":\"chatcmpl-tool\",\"object\":\"chat.completion.chunk\",\"created\":1677652288,\"model\":\"test-model\",\"choices\":[{\"index\":0,\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\"{\\\"lo\"}}]},\"finish_reason\":null}]}\n\n",
        "data: {\"id\":\"chatcmpl-tool\",\"object\":\"chat.completion.chunk\",\"created\":1677652288,\"model\":\"test-model\",\"choices\":[{\"index\":0,\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\"cation\"}}]},\"finish_reason\":null}]}\n\n",
        "data: {\"id\":\"chatcmpl-tool\",\"object\":\"chat.completion.chunk\",\"created\":1677652288,\"model\":\"test-model\",\"choices\":[{\"index\":0,\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n\n",
        "data: [DONE]\n\n",
    ];

    let combined: String = chunks.concat();

    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_string(combined)
                .append_header("Content-Type", "text/event-stream")
        )
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_chat_model(config, "test-model").unwrap();

    let prompt = Prompt::with_user("What's the weather?");
    let options = CallOptions::default();
    
    let stream = model.do_stream(prompt, options).await.unwrap();
    
    let mut tool_call_started = false;
    let mut finish_reason = None;
    
    use futures::StreamExt;
    let mut stream = stream;
    
    while let Some(part) = stream.next().await {
        match part.unwrap() {
            ai_sdk_openai_compatible::StreamPart::ToolCallStart { .. } => {
                tool_call_started = true;
            }
            ai_sdk_openai_compatible::StreamPart::ToolCallDelta { arguments, .. } => {
                assert!(!arguments.is_empty());
            }
            ai_sdk_openai_compatible::StreamPart::Finish { reason, .. } => {
                finish_reason = Some(reason);
            }
            _ => {}
        }
    }

    assert!(tool_call_started);
    assert_eq!(finish_reason, Some(ai_sdk_openai_compatible::FinishReason::ToolCalls));
}

#[tokio::test]
async fn test_api_error_handling() {
    let mock_server = MockServer::start().await;

    let error_body = serde_json::json!({
        "error": {
            "message": "Invalid API key",
            "type": "invalid_request_error",
            "code": "invalid_api_key"
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .respond_with(ResponseTemplate::new(401).set_body_json(&error_body))
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_chat_model(config, "test-model").unwrap();

    let prompt = Prompt::with_user("Hello");
    let options = CallOptions::default();
    
    let result = model.do_generate(prompt, options).await;
    
    assert!(result.is_err());
}
