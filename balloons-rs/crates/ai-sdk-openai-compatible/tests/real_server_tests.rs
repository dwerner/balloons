//! Integration tests with real LLM servers.

use ai_sdk_openai_compatible::{
    create_chat_model, CallOptions, LanguageModel, Message, Prompt, ProviderConfig,
};

const REAL_SERVER_URL: &str = "http://192.168.0.196:8000";

#[tokio::test]
async fn test_real_server_simple_chat() {
    let config = ProviderConfig::new(REAL_SERVER_URL);
    let model = create_chat_model(config, "test-model").unwrap();

    let prompt = Prompt::with_user("Hello, respond with just 'OK'");
    let options = CallOptions {
        max_tokens: Some(10),
        ..Default::default()
    };
    
   let result = model.do_generate(prompt, options).await;
    
    // Just confirm we get a response (don't check exact content as models vary)
    if result.is_err() {
        eprintln!("Error: {:?}", result.as_ref().unwrap_err());
    }
    assert!(result.is_ok(), "API call failed: {:?}", result.as_ref().err());
    let result = result.unwrap();
    // Server may return reasoning_content instead of content
    assert!(result.text.is_some() || result.reasoning.is_some());
    println!("Server response - text: {:?}, reasoning: {:?}", result.text, result.reasoning);
}

#[tokio::test]
async fn test_real_server_with_system_prompt() {
    let config = ProviderConfig::new(REAL_SERVER_URL);
    let model = create_chat_model(config, "test-model").unwrap();

    let mut prompt = Prompt::with_system("You are a test assistant.");
    prompt.messages.push(Message::user("Say 'test passed'"));
    
    let options = CallOptions {
        max_tokens: Some(20),
        ..Default::default()
    };
    
    let result = model.do_generate(prompt, options).await;
    
    assert!(result.is_ok());
    let result = result.unwrap();
    println!("Server response with system prompt: {:?}", result.text);
}

#[tokio::test]
async fn test_real_server_streaming() {
    use futures::StreamExt;

    let config = ProviderConfig::new(REAL_SERVER_URL);
    let model = create_chat_model(config, "test-model").unwrap();

    let prompt = Prompt::with_user("Count to 3");
    let options = CallOptions {
        max_tokens: Some(20),
        ..Default::default()
    };
    
    let stream = model.do_stream(prompt, options).await;
    
    assert!(stream.is_ok());
    let mut stream = stream.unwrap();
    
    let mut token_count = 0;
    let mut has_reasoning = false;
    while let Some(part) = stream.next().await {
        match part {
            Ok(ai_sdk_openai_compatible::StreamPart::TextDelta { .. }) => {
                token_count += 1;
            }
            Ok(ai_sdk_openai_compatible::StreamPart::ReasoningDelta { .. }) => {
                has_reasoning = true;
            }
            Ok(ai_sdk_openai_compatible::StreamPart::Finish { .. }) => {
                break;
            }
            Ok(_) => {}
            Err(e) => {
                eprintln!("Stream error: {:?}", e);
                break;
            }
        }
    }
    
    // Should have received at least some tokens or reasoning
    assert!(token_count > 0 || has_reasoning, "Expected to receive some tokens or reasoning, got {} tokens and reasoning={}", token_count, has_reasoning);
    println!("Received {} tokens and reasoning={} via streaming", token_count, has_reasoning);
}
