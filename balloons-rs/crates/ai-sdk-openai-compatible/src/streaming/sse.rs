//! SSE (Server-Sent Events) parser.

use futures::StreamExt;
use std::pin::Pin;

/// Parse SSE stream into events.
pub async fn parse_sse_stream(
    response: reqwest::Response,
) -> Result<
    Pin<Box<dyn futures::Stream<Item = Result<SseEvent, crate::Error>> + Send>>,
    crate::Error,
> {
    
    let mut stream = response.bytes_stream();
    
    let parsed = async_stream::try_stream! {
        let mut buffer = String::new();
        
        while let Some(chunk_result) = stream.next().await {
            let chunk = chunk_result.map_err(|e| {
                crate::Error::StreamingError(e.to_string())
            })?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));
            
            // Parse SSE events (simplified - just extract data lines)
            while let Some(pos) = buffer.find('\n') {
                let line = buffer[..pos].trim().to_string();
                buffer = buffer[pos + 1..].to_string();
                
                if line.starts_with("data:") {
                    let data = line[5..].trim().to_string();
                    if data != "[DONE]" {
                        yield SseEvent {
                            event: None,
                            data,
                            id: None,
                        };
                    }
                }
            }
        }
    };

    Ok(Box::pin(parsed))
}

/// An SSE event.
#[derive(Debug, Clone)]
pub struct SseEvent {
    pub event: Option<String>,
    pub data: String,
    pub id: Option<String>,
}
