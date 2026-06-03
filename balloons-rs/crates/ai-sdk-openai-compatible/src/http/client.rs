//! HTTP client wrapper.

use crate::error::{ApiCallError, Error};
use reqwest::Client;
use serde::{de::DeserializeOwned, Serialize};

/// HTTP client for API calls.
pub struct HttpClient {
    client: Client,
    base_url: String,
    headers: reqwest::header::HeaderMap,
}

impl HttpClient {
    pub fn new(base_url: impl Into<String>) -> Result<Self, Error> {
        let client = Client::builder()
            .timeout(std::time::Duration::from_secs(120))
            .build()
            .map_err(ApiCallError::Http)?;

        let headers = reqwest::header::HeaderMap::new();

        Ok(Self {
            client,
            base_url: base_url.into(),
            headers,
        })
    }

    pub fn with_headers(mut self, headers: reqwest::header::HeaderMap) -> Self {
        self.headers = headers;
        self
    }

    pub fn with_api_key(mut self, api_key: &str) -> Self {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::AUTHORIZATION,
            format!("Bearer {}", api_key)
                .parse()
                .expect("Invalid authorization header"),
        );
        self.headers.extend(headers);
        self
    }

    /// POST JSON to an endpoint.
    pub async fn post_json<T, R>(
        &self,
        path: &str,
        body: &T,
    ) -> Result<R, Error>
    where
        T: Serialize + ?Sized,
        R: DeserializeOwned,
    {
        let url = format!("{}{}", self.base_url, path);

        let response = self
            .client
            .post(&url)
            .headers(self.headers.clone())
            .json(body)
            .send()
            .await
            .map_err(ApiCallError::from)?;

        self.handle_response(response).await
    }

    /// POST JSON and get streaming response.
    pub async fn post_json_stream(
        &self,
        path: &str,
        body: &impl Serialize,
    ) -> Result<reqwest::Response, Error> {
        let url = format!("{}{}", self.base_url, path);

        let response = self
            .client
            .post(&url)
            .headers(self.headers.clone())
            .json(body)
            .send()
            .await
            .map_err(ApiCallError::from)?;

        Ok(response)
    }

    async fn handle_response<R: DeserializeOwned>(
        &self,
        response: reqwest::Response,
    ) -> Result<R, Error> {
        let status = response.status();

        if !status.is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(Error::ApiCall(ApiCallError::Network(format!(
                "HTTP {}: {}",
                status,
                error_text
            ))));
        }

       match response.json::<R>().await {
            Ok(v) => Ok(v),
            Err(e) => Err(Error::ApiCall(ApiCallError::Network(format!(
                "Failed to parse JSON response: {}",
                e
            )))),
        }
    }
}
