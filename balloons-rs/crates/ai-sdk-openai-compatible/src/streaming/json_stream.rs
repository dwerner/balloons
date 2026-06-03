//! JSON stream parser for NDJSON and similar formats.

use std::pin::Pin;
use futures::StreamExt;
use serde::de::DeserializeOwned;

/// Parse a stream of JSON lines (NDJSON).
pub async fn parse_json_stream<T: DeserializeOwned + Send + 'static>(
    response: reqwest::Response,
) -> Result<
    Pin<Box<dyn futures::Stream<Item = Result<T, crate::Error>> + Send>>,
    crate::Error,
> {
    let mut lines = response.bytes_stream();
    let parsed = async_stream::try_stream! {
        let mut buffer = String::new();
        while let Some(chunk_result) = lines.next().await {
            let chunk = chunk_result.map_err(|e| {
                crate::Error::StreamingError(e.to_string())
            })?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            while let Some(pos) = buffer.find('\n') {
                let line = buffer[..pos].trim().to_string();
                buffer = buffer[pos + 1..].to_string();

                if line.is_empty() {
                    continue;
                }

                let value: T = serde_json::from_str(&line)
                    .map_err(|e| crate::Error::InvalidJson(e))?;
                yield value;
            }
        }
    };

    Ok(Box::pin(parsed))
}
