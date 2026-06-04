//! OpenAI-compatible chat language model.

use async_trait::async_trait;
use futures::StreamExt;

use crate::chat::messages::convert_to_chat_messages;
use crate::chat::tools::{parse_tool_calls, prepare_tool_choice, prepare_tools};
use crate::chat::types::{
    ChatCompletionChunk, ChatCompletionRequest, ChatCompletionResponse,
};
use crate::error::Error;
use crate::http::HttpClient;
use crate::streaming::parse_sse_stream;
use crate::types::{
    CallOptions, FinishReason, GenerateResult, LanguageModel,
    LanguageModelStream, Prompt, StreamPart, Usage,
};

/// Configuration for the OpenAI-compatible chat model.
#[derive(Debug, Clone)]
pub struct ChatConfig {
    pub base_url: String,
    pub model_id: String,
    pub api_key: Option<String>,
    pub headers: reqwest::header::HeaderMap,
}

/// OpenAI-compatible chat language model.
pub struct OpenAICompatibleChatModel {
    config: ChatConfig,
    client: HttpClient,
}

impl OpenAICompatibleChatModel {
    pub fn new(config: ChatConfig) -> Result<Self, Error> {
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

    /// Build the request body.
    fn build_request(&self, prompt: &Prompt, options: &CallOptions) -> ChatCompletionRequest {
        let messages = convert_to_chat_messages(prompt);

        ChatCompletionRequest {
            model: self.config.model_id.clone(),
            messages,
            temperature: options.temperature,
            top_p: options.top_p,
            n: options.n,
            stream: Some(false),
            stop: options.stop.clone(),
            max_tokens: options.max_tokens,
            presence_penalty: options.presence_penalty,
            frequency_penalty: options.frequency_penalty,
            logit_bias: None,
            user: None,
            tools: options.tools.as_ref().map(|t| prepare_tools(t)),
            tool_choice: options.tool_choice.as_ref().and_then(prepare_tool_choice),
            response_format: None,
            seed: options.seed,
        }
    }

    /// Build the streaming request body.
    fn build_streaming_request(
        &self,
        prompt: &Prompt,
        options: &CallOptions,
    ) -> ChatCompletionRequest {
        let mut request = self.build_request(prompt, options);
        request.stream = Some(true);
        request
    }
}

#[async_trait]
impl LanguageModel for OpenAICompatibleChatModel {
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

        let response: ChatCompletionResponse = self
            .client
            .post_json("/v1/chat/completions", &request)
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
            Some("tool_calls") => FinishReason::ToolCalls,
            Some("content_filter") => FinishReason::ContentFilter,
            _ => FinishReason::Other,
        };

        let mut text = None;
        let mut reasoning = None;
        let mut tool_calls = Vec::new();

        if let Some(ref reasoning_content) = choice.message.reasoning_content {
            if !reasoning_content.is_empty() {
                reasoning = Some(reasoning_content.clone());
            }
        }

        if let Some(ref content) = choice.message.content {
            if !content.is_empty() {
                text = Some(content.clone());
            }
        }

        if let Some(ref calls) = choice.message.tool_calls {
            tool_calls = parse_tool_calls(calls);
        }

        Ok(GenerateResult {
            response_id: response.id,
            text,
            reasoning,
            tool_calls,
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

        // Need to make blocking call to get response for streaming
        let response = self
            .client
            .post_json_stream("/v1/chat/completions", &request)
            .await?;

        let stream = parse_sse_stream(response).await?;
        let parsed = stream
            .filter_map(move |result| async move {
                match result {
                    Ok(event) => {
                        if event.data == "[DONE]" {
                            return None;
                        }

                        match serde_json::from_str::<ChatCompletionChunk>(&event.data) {
                            Ok(chunk) => {
                                let choice = &chunk.choices[0];

                                // Extract text delta
                                if let Some(ref content) = choice.delta.content {
                                    if !content.is_empty() {
                                        return Some(Ok(StreamPart::TextDelta {
                                            delta: content.clone(),
                                        }));
                                    }
                                }

                                // Extract reasoning delta
                                if let Some(ref reasoning) = choice.delta.reasoning_content {
                                    if !reasoning.is_empty() {
                                        return Some(Ok(StreamPart::ReasoningDelta {
                                            delta: reasoning.clone(),
                                        }));
                                    }
                                }

                                // Extract tool call deltas
                                if let Some(ref calls) = choice.delta.tool_calls {
                                    for call in calls {
                                        if let Some(ref function) = call.function {
                                            let tool_id = call.id.clone().unwrap_or_default();
                                            
                                            // Always send ToolCallDelta with name and arguments when available
                                            // This handles both incremental deltas and complete tool calls in one chunk
                                            if let Some(ref args) = function.arguments {
                                                return Some(Ok(StreamPart::ToolCallDelta {
                                                    id: tool_id,
                                                    name: function.name.clone(),
                                                    arguments: args.clone(),
                                                }));
                                            }
                                            
                                            // If we have a name but no arguments yet, send ToolCallStart
                                            if function.name.is_some() {
                                                return Some(Ok(StreamPart::ToolCallStart {
                                                    id: tool_id,
                                                }));
                                            }
                                        }
                                    }
                                }

                                // Check for finish - send ToolCallEnd before Finish if tool_calls
                                if let Some(ref reason) = choice.finish_reason {
                                    if reason == "tool_calls" {
                                        // Send ToolCallEnd for all tool calls in this chunk
                                        if let Some(ref calls) = choice.delta.tool_calls {
                                            for call in calls {
                                                return Some(Ok(StreamPart::ToolCallEnd {
                                                    id: call.id.clone().unwrap_or_default(),
                                                }));
                                            }
                                        }
                                    }
                                    
                                    let finish_reason = match reason.as_str() {
                                        "stop" => FinishReason::Stop,
                                        "length" => FinishReason::Length,
                                        "tool_calls" => FinishReason::ToolCalls,
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
