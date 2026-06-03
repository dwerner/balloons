//! Response handling utilities.

use serde::de::DeserializeOwned;

/// Handle API response and extract JSON.
pub async fn handle_json_response<R: DeserializeOwned>(
    response: reqwest::Response,
) -> Result<R, crate::Error> {
    let status = response.status();

    if !status.is_success() {
        let error_body = response.text().await.unwrap_or_default();
        return Err(crate::Error::ApiCall(crate::error::ApiCallError::Network(format!(
            "HTTP {}: {}",
            status, error_body
        ))));
    }

    match response.json::<R>().await {
        Ok(v) => Ok(v),
        Err(e) => Err(crate::Error::ApiCall(crate::error::ApiCallError::Network(format!(
            "Failed to parse JSON response: {}",
            e
        )))),
    }
}

/// Extract response headers.
pub fn extract_response_headers(
    response: &reqwest::Response,
) -> std::collections::HashMap<String, String> {
    response
        .headers()
        .iter()
        .filter_map(|(name, value)| {
            name.as_str()
                .parse()
                .ok()
                .and_then(|name: String| value.to_str().ok().map(|value| (name, value.to_string())))
        })
        .collect()
}
