//! Internal HTTP transport types.

use http::{HeaderMap, Method, StatusCode};

/// A fully materialized outbound HTTP request.
#[derive(Debug, Clone)]
pub struct RequestData {
    /// HTTP method.
    pub method: Method,
    /// Absolute URL.
    pub url: String,
    /// HTTP headers.
    pub headers: HeaderMap,
    /// Request body bytes.
    pub body: Vec<u8>,
}

/// A fully materialized inbound HTTP response.
#[derive(Debug, Clone)]
pub struct ResponseData {
    /// HTTP status code.
    pub status: StatusCode,
    /// HTTP headers.
    pub headers: HeaderMap,
    /// Response body bytes.
    pub body: Vec<u8>,
}
