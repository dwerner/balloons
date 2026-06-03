//! Text completion tests.

use ai_sdk_openai_compatible::{
    create_completion_model, CallOptions, LanguageModel, Prompt, ProviderConfig,
};
use wiremock::{
    matchers::{method, path},
    Mock, MockServer, ResponseTemplate,
};

#[tokio::test]
async fn test_simple_completion() {
    // Start mock server
    let mock_server = MockServer::start().await;

    // Mock response
    let response_body = serde_json::json!({
        "id": "cmpl-123",
        "object": "text_completion",
        "created": 1677652288,
        "model": "test-model",
        "choices": [{
            "text": "This is the completion",
            "index": 0,
            "logprobs": null,
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 5,
            "total_tokens": 10
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/completions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
        .mount(&mock_server)
        .await;

    // Create model
    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_completion_model(config, "test-model").unwrap();

    // Make request
    let prompt = Prompt::with_user("Complete this: This is");
    let options = CallOptions::default();
    let result = model.do_generate(prompt, options).await.unwrap();

    // Verify
    assert_eq!(result.response_id, "cmpl-123");
    assert_eq!(result.text, Some("This is the completion".to_string()));
    assert_eq!(result.usage.input_tokens, 5);
    assert_eq!(result.usage.output_tokens, 5);
}

#[tokio::test]
async fn test_completion_with_system_prompt() {
    // Start mock server
    let mock_server = MockServer::start().await;

    // Mock response
    let response_body = serde_json::json!({
        "id": "cmpl-456",
        "object": "text_completion",
        "created": 1677652288,
        "model": "test-model",
        "choices": [{
            "text": "System prompt was processed",
            "index": 0,
            "logprobs": null,
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/completions"))
        .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
        .mount(&mock_server)
        .await;

    // Create model
    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_completion_model(config, "test-model").unwrap();

    // Make request with system prompt
    let mut prompt = Prompt::with_system("You are a helpful assistant");
    prompt.messages.push(Prompt::with_user("Say test").messages[0].clone());
    
    let options = CallOptions {
        max_tokens: Some(20),
        ..Default::default()
    };
    let result = model.do_generate(prompt, options).await.unwrap();

    // Verify
    assert_eq!(result.text, Some("System prompt was processed".to_string()));
}

#[tokio::test]
async fn test_completion_streaming() {
    use futures::StreamExt;

    // Start mock server
    let mock_server = MockServer::start().await;

    // Mock streaming response
    let chunk1 = "data: {\"id\":\"cmpl-789\",\"object\":\"text_completion\",\"created\":123,\"model\":\"test-model\",\"choices\":[{\"text\":\"Hello\",\"index\":0,\"finish_reason\":null}]}";
    let chunk2 = "data: {\"id\":\"cmpl-789\",\"object\":\"text_completion\",\"created\":123,\"model\":\"test-model\",\"choices\":[{\"text\":\" world\",\"index\":0,\"finish_reason\":null}]}";
    let chunk3 = "data: {\"id\":\"cmpl-789\",\"object\":\"text_completion\",\"created\":123,\"model\":\"test-model\",\"choices\":[{\"text\":\"!\",\"index\":0,\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":2,\"completion_tokens\":3,\"total_tokens\":5}}";
    let chunk4 = "data: [DONE]";

    Mock::given(method("POST"))
        .and(path("/v1/completions"))
        .respond_with(ResponseTemplate::new(200).set_body_string(format!("{}\n{}\n{}\n{}", chunk1, chunk2, chunk3, chunk4)))
        .mount(&mock_server)
        .await;

    // Create model
    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_completion_model(config, "test-model").unwrap();

    // Make streaming request
    let prompt = Prompt::with_user("Say hello");
    let options = CallOptions::default();
    let stream = model.do_stream(prompt, options).await.unwrap();

    // Collect stream
    let mut tokens = Vec::new();
    tokio::pin!(stream);
    
    while let Some(part) = stream.next().await {
        match part {
            Ok(ai_sdk_openai_compatible::StreamPart::TextDelta { delta }) => {
                tokens.push(delta);
            }
            Ok(ai_sdk_openai_compatible::StreamPart::Finish { usage, .. }) => {
                assert!(usage.is_some());
                assert_eq!(usage.unwrap().total_tokens, 5);
            }
            _ => {}
        }
    }

    // Verify
    assert_eq!(tokens.join(""), "Hello world!");
}

#[tokio::test]
async fn test_completion_error_handling() {
    // Start mock server
    let mock_server = MockServer::start().await;

    // Mock error response
    let error_body = serde_json::json!({
        "error": {
            "message": "Invalid model",
            "type": "invalid_request_error",
            "code": 400
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/completions"))
        .respond_with(ResponseTemplate::new(400).set_body_json(&error_body))
        .mount(&mock_server)
        .await;

    // Create model
    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_completion_model(config, "test-model").unwrap();

    // Make request
    let prompt = Prompt::with_user("Test");
    let result = model.do_generate(prompt, CallOptions::default()).await;

    // Verify error
    assert!(result.is_err());
}
