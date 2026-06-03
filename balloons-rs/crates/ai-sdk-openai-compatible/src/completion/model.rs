//! OpenAI-compatible text completion model.

use async_trait::async_trait;
use futures::StreamExt;

use crate::completion::types::{
    CompletionChunk, CompletionRequest, CompletionResponse,
};
use crate::error::Error;
use crate::http::HttpClient;
use crate::streaming::parse_sse_stream;
use crate::types::{
    CallOptions, ContentPart, FinishReason, GenerateResult, LanguageModel,
    LanguageModelStream, Message, Prompt, StreamPart, Usage,
};

/// Configuration for the completion model.
#[derive(Debug, Clone)]
pub struct CompletionConfig {
    pub base_url: String,
    pub model_id: String,
    pub api_key: Option<String>,
    pub headers: reqwest::header::HeaderMap,
}

/// OpenAI-compatible text completion model.
pub struct OpenAICompatibleCompletionModel {
    config: CompletionConfig,
    client: HttpClient,
}

impl OpenAICompatibleCompletionModel {
    pub fn new(config: CompletionConfig) -> Result<Self, Error> {
        let mut client = HttpClient::new(&config.base_url)?;

        if let Some(ref api_key) = config.api_key {
            client = client.with_api_key(api_key);
        }

        if !config.headers.is_empty() {
            client = client.with_headers(config.headers.clone());
        }

        Ok(Self {
            config,
            client,
        })
    }

    /// Convert prompt to completion-style prompt string.
    fn prompt_to_string(prompt: &Prompt) -> String {
        let mut text = String::new();

        for message in &prompt.messages {
            match message {
                Message::System(m) => {
                    text.push_str(&m.content);
                    text.push_str("\n\n");
                }
                Message::User(m) => {
                    text.push_str("user:\n");
                    if let Some(ContentPart::Text(c)) = m.content.first() {
                        text.push_str(&c.text);
                    }
                    text.push_str("\n\n");
                }
                Message::Assistant(m) => {
                    text.push_str("assistant:\n");
                    if let Some(ContentPart::Text(c)) = m.content.first() {
                        text.push_str(&c.text);
                    }
                    text.push_str("\n\n");
                }
                Message::Tool(_) => {}
            }
        }

        text
    }

    /// Build the request body.
    fn build_request(&self, prompt: &Prompt, options: &CallOptions) -> CompletionRequest {
        let prompt_text = Self::prompt_to_string(prompt);

        CompletionRequest {
            model: self.config.model_id.clone(),
            prompt: prompt_text,
            best_of: None,
            echo: None,
            frequency_penalty: options.frequency_penalty,
            logit_bias: None,
            logprobs: None,
            max_tokens: options.max_tokens,
            n: options.n,
            presence_penalty: options.presence_penalty,
            seed: options.seed,
            stop: options.stop.clone(),
            stream: Some(false),
            suffix: None,
            temperature: options.temperature,
            top_p: options.top_p,
            user: None,
        }
    }

    /// Build the streaming request body.
    fn build_streaming_request(
        &self,
        prompt: &Prompt,
        options: &CallOptions,
    ) -> CompletionRequest {
        let mut request = self.build_request(prompt, options);
        request.stream = Some(true);
        request
    }
}

#[async_trait]
impl LanguageModel for OpenAICompatibleCompletionModel {
    fn provider(&self) -> &str {
        "openai-compatible"
    }

    fn model_id(&self) -> &str {
        &self.config.model_id
    }

    async fn do_generate(
        &self,
        prompt: Prompt,
        options: CallOptions,
    ) -> Result<GenerateResult, Error> {
        let request = self.build_request(&prompt, &options);

        let response: CompletionResponse = self
            .client
            .post_json("/v1/completions", &request)
            .await?;

        let choice = &response.choices[0];
        let usage = response.usage.as_ref().map(|u| Usage {
            input_tokens: u.prompt_tokens,
            output_tokens: u.completion_tokens,
            total_tokens: u.total_tokens,
        });

        let finish_reason = match choice.finish_reason.as_deref() {
            Some("stop") => FinishReason::Stop,
            Some("length") => FinishReason::Length,
            Some("content_filter") => FinishReason::ContentFilter,
            _ => FinishReason::Other,
        };

        Ok(GenerateResult {
            response_id: response.id,
            text: Some(choice.text.clone()),
            reasoning: None,
            tool_calls: Vec::new(),
            usage: usage.unwrap_or_default(),
            finish_reason,
            provider_metadata: serde_json::Value::Null,
        })
    }

    async fn do_stream(
        &self,
        prompt: Prompt,
        options: CallOptions,
    ) -> Result<LanguageModelStream, Error> {
        let request = self.build_streaming_request(&prompt, &options);

        let response = self
            .client
            .post_json_stream("/v1/completions", &request)
            .await?;

        let stream = parse_sse_stream(response).await?;
        let parsed = stream
            .filter_map(move |result| async move {
                match result {
                    Ok(event) => {
                        if event.data == "[DONE]" {
                            return None;
                        }

                        match serde_json::from_str::<CompletionChunk>(&event.data) {
                            Ok(chunk) => {
                                let choice = &chunk.choices[0];

                                // Extract text delta
                                if !choice.text.is_empty() {
                                    return Some(Ok(StreamPart::TextDelta {
                                        delta: choice.text.clone(),
                                    }));
                                }

                                // Check for finish
                                if let Some(ref reason) = choice.finish_reason {
                                    let finish_reason = match reason.as_str() {
                                        "stop" => FinishReason::Stop,
                                        "length" => FinishReason::Length,
                                        "content_filter" => FinishReason::ContentFilter,
                                        _ => FinishReason::Other,
                                    };

                                    return Some(Ok(StreamPart::Finish {
                                        reason: finish_reason,
                                        usage: chunk.usage.map(|u| Usage {
                                            input_tokens: u.prompt_tokens,
                                            output_tokens: u.completion_tokens,
                                            total_tokens: u.total_tokens,
                                        }),
                                    }));
                                }

                                None
                            }
                            Err(e) => Some(Err(Error::InvalidJson(e))),
                        }
                    }
                    Err(e) => Some(Err(e)),
                }
            });

        Ok(Box::pin(parsed))
    }
}
