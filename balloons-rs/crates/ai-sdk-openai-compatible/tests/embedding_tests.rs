//! Embedding model tests.

use ai_sdk_openai_compatible::{
    create_embedding_model, EmbeddingOptions, ProviderConfig,
};
use wiremock::{
    matchers::{method, path},
    Mock, MockServer, ResponseTemplate,
};

const DUMMY_EMBEDDINGS: [[f32; 5]; 2] = [
    [0.1, 0.2, 0.3, 0.4, 0.5],
    [0.6, 0.7, 0.8, 0.9, 1.0],
];

const TEST_VALUES: [&str; 2] = ["sunny day at the beach", "rainy day in the city"];

#[tokio::test]
async fn test_simple_embedding() {
    let mock_server = MockServer::start().await;

    let response_body = serde_json::json!({
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "index": 0,
                "embedding": DUMMY_EMBEDDINGS[0]
            },
            {
                "object": "embedding",
                "index": 1,
                "embedding": DUMMY_EMBEDDINGS[1]
            }
        ],
        "model": "text-embedding-3-large",
        "usage": {
            "prompt_tokens": 8,
            "total_tokens": 8
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/embeddings"))
        .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_embedding_model(config, "text-embedding-3-large").unwrap();

    let values: Vec<String> = TEST_VALUES.iter().map(|s| s.to_string()).collect();
    let result = model.do_embed(values, EmbeddingOptions::default()).await.unwrap();

    assert_eq!(result.embeddings.len(), 2);
    assert_eq!(result.embeddings[0], DUMMY_EMBEDDINGS[0]);
    assert_eq!(result.embeddings[1], DUMMY_EMBEDDINGS[1]);
    assert_eq!(result.usage.input_tokens, 8);
}

#[tokio::test]
async fn test_embedding_with_dimensions() {
    let mock_server = MockServer::start().await;

    let response_body = serde_json::json!({
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "index": 0,
                "embedding": [0.1, 0.2, 0.3]
            }
        ],
        "model": "text-embedding-3-large",
        "usage": {
            "prompt_tokens": 5,
            "total_tokens": 5
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/embeddings"))
        .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_embedding_model(config, "text-embedding-3-large").unwrap();

    let values = vec!["test text".to_string()];
    let options = EmbeddingOptions {
        dimensions: Some(3),
        user: None,
    };
    let result = model.do_embed(values, options).await.unwrap();

    assert_eq!(result.embeddings[0].len(), 3);
}

#[tokio::test]
async fn test_embedding_error_handling() {
    let mock_server = MockServer::start().await;

    let error_body = serde_json::json!({
        "error": {
            "message": "Invalid model",
            "type": "invalid_request_error",
            "code": 400
        }
    });

    Mock::given(method("POST"))
        .and(path("/v1/embeddings"))
        .respond_with(ResponseTemplate::new(400).set_body_json(&error_body))
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_embedding_model(config, "text-embedding-3-large").unwrap();

    let values = vec!["test".to_string()];
    let result = model.do_embed(values, EmbeddingOptions::default()).await;

    assert!(result.is_err());
}

#[tokio::test]
async fn test_embedding_no_usage() {
    let mock_server = MockServer::start().await;

    let response_body = serde_json::json!({
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "index": 0,
                "embedding": [0.1, 0.2, 0.3]
            }
        ],
        "model": "text-embedding-3-large"
    });

    Mock::given(method("POST"))
        .and(path("/v1/embeddings"))
        .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
        .mount(&mock_server)
        .await;

    let config = ProviderConfig::new(&mock_server.uri());
    let model = create_embedding_model(config, "text-embedding-3-large").unwrap();

    let values = vec!["test".to_string()];
    let result = model.do_embed(values, EmbeddingOptions::default()).await.unwrap();

    assert_eq!(result.embeddings.len(), 1);
    // Usage should have default values when not provided
    assert_eq!(result.usage.input_tokens, 0);
    assert_eq!(result.usage.output_tokens, 0);
    assert_eq!(result.usage.total_tokens, 0);
}
