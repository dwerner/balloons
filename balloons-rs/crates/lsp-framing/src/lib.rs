//! LSP Content-Length framing parser using nom.
//!
//! The LSP base protocol uses HTTP-style headers to frame JSON-RPC messages:
//!
//! ```text
//! Content-Length: 234\r\n
//! Content-Type: application/vscode-jsonrpc; charset=utf-8\r\n
//! \r\n
//! {"jsonrpc":"2.0","id":1,"method":"initialize",...}
//! ```
//!
//! This crate provides:
//! - A nom parser for the header section
//! - A streaming decoder that handles partial reads
//! - An encoder for outgoing messages

use bytes::{Buf, BytesMut};
use nom::{
    IResult, Parser,
    branch::alt,
    bytes::complete::{tag, tag_no_case, take_until, take_while1},
    character::complete::{char, digit1, space0},
    combinator::map_res,
    multi::many0,
    sequence::terminated,
};
use std::str;
use thiserror::Error;

/// Errors that can occur during LSP framing.
#[derive(Debug, Error)]
pub enum FrameError {
    #[error("Invalid Content-Length value: {0}")]
    InvalidContentLength(String),

    #[error("Missing Content-Length header")]
    MissingContentLength,

    #[error("Invalid header format: {0}")]
    InvalidHeader(String),

    #[error("Content-Length exceeds maximum ({max} bytes)")]
    ContentTooLarge { max: usize },

    #[error("Invalid UTF-8 in message")]
    InvalidUtf8,
}

/// A parsed LSP header.
#[derive(Debug, Clone, PartialEq)]
pub enum Header {
    ContentLength(usize),
    ContentType(String),
    Other { name: String, value: String },
}

/// A complete LSP message frame.
#[derive(Debug, Clone)]
pub struct Frame {
    pub content_length: usize,
    pub content_type: Option<String>,
    pub content: String,
}

/// Parse the header name (case-insensitive for Content-Length/Content-Type).
fn header_name(input: &[u8]) -> IResult<&[u8], &[u8]> {
    take_while1(|c: u8| c != b':' && c != b'\r' && c != b'\n').parse(input)
}

/// Parse the header value (everything until CRLF).
fn header_value(input: &[u8]) -> IResult<&[u8], &[u8]> {
    take_until("\r\n").parse(input)
}

/// Parse a Content-Length header.
fn content_length_header(input: &[u8]) -> IResult<&[u8], Header> {
    let (input, _) = tag_no_case::<_, _, nom::error::Error<&[u8]>>("Content-Length".as_bytes()).parse(input)?;
    let (input, _) = char(':').parse(input)?;
    let (input, _) = space0.parse(input)?;
    let (input, len) = map_res(
        map_res(digit1, str::from_utf8),
        |s: &str| s.parse::<usize>(),
    ).parse(input)?;
    let (input, _) = tag("\r\n").parse(input)?;
    Ok((input, Header::ContentLength(len)))
}

/// Parse a Content-Type header.
fn content_type_header(input: &[u8]) -> IResult<&[u8], Header> {
    let (input, _) = tag_no_case::<_, _, nom::error::Error<&[u8]>>("Content-Type".as_bytes()).parse(input)?;
    let (input, _) = char(':').parse(input)?;
    let (input, _) = space0.parse(input)?;
    let (input, value) = map_res(header_value, str::from_utf8).parse(input)?;
    let (input, _) = tag("\r\n").parse(input)?;
    Ok((input, Header::ContentType(value.trim().to_string())))
}

/// Parse any other header.
fn other_header(input: &[u8]) -> IResult<&[u8], Header> {
    let (input, name) = map_res(header_name, str::from_utf8).parse(input)?;
    let (input, _) = char(':').parse(input)?;
    let (input, _) = space0.parse(input)?;
    let (input, value) = map_res(header_value, str::from_utf8).parse(input)?;
    let (input, _) = tag("\r\n").parse(input)?;
    Ok((
        input,
        Header::Other {
            name: name.to_string(),
            value: value.trim().to_string(),
        },
    ))
}

/// Parse a single header line.
fn header(input: &[u8]) -> IResult<&[u8], Header> {
    alt((content_length_header, content_type_header, other_header)).parse(input)
}

/// Parse all headers until the empty line.
fn headers(input: &[u8]) -> IResult<&[u8], Vec<Header>> {
    terminated(many0(header), tag("\r\n")).parse(input)
}

/// Streaming decoder for LSP messages.
///
/// Handles partial reads by buffering data until a complete message is available.
pub struct Decoder {
    buffer: BytesMut,
    max_message_size: usize,
}

impl Default for Decoder {
    fn default() -> Self {
        Self::new()
    }
}

impl Decoder {
    /// Create a new decoder with default max message size (16MB).
    pub fn new() -> Self {
        Self {
            buffer: BytesMut::with_capacity(8192),
            max_message_size: 16 * 1024 * 1024,
        }
    }

    /// Create a new decoder with custom max message size.
    pub fn with_max_size(max_message_size: usize) -> Self {
        Self {
            buffer: BytesMut::with_capacity(8192),
            max_message_size,
        }
    }

    /// Feed data into the decoder.
    pub fn feed(&mut self, data: &[u8]) {
        self.buffer.extend_from_slice(data);
    }

    /// Try to decode a complete message.
    ///
    /// Returns:
    /// - `Ok(Some(frame))` if a complete message was decoded
    /// - `Ok(None)` if more data is needed
    /// - `Err(e)` if there was a parsing error
    pub fn decode(&mut self) -> Result<Option<Frame>, FrameError> {
        // Check if we have the header terminator (empty line)
        // This is a fast path to avoid parsing incomplete headers
        if !self.buffer.windows(4).any(|w| w == b"\r\n\r\n") {
            return Ok(None);
        }

        // Try to parse headers
        let (remaining, hdrs) = match headers(&self.buffer) {
            Ok(result) => result,
            Err(nom::Err::Incomplete(_)) => return Ok(None),
            Err(nom::Err::Error(e)) | Err(nom::Err::Failure(e)) => {
                return Err(FrameError::InvalidHeader(format!(
                    "Parse error at byte {}",
                    self.buffer.len() - e.input.len()
                )));
            }
        };

        // Extract content length
        let content_length = hdrs
            .iter()
            .find_map(|h| match h {
                Header::ContentLength(len) => Some(*len),
                _ => None,
            })
            .ok_or(FrameError::MissingContentLength)?;

        // Check size limit
        if content_length > self.max_message_size {
            return Err(FrameError::ContentTooLarge {
                max: self.max_message_size,
            });
        }

        // Extract content type if present
        let content_type = hdrs.iter().find_map(|h| match h {
            Header::ContentType(ct) => Some(ct.clone()),
            _ => None,
        });

        // Check if we have enough data for the content
        if remaining.len() < content_length {
            return Ok(None);
        }

        // Extract the content
        let content = str::from_utf8(&remaining[..content_length])
            .map_err(|_| FrameError::InvalidUtf8)?
            .to_string();

        // Calculate how much of the buffer we consumed
        let headers_len = self.buffer.len() - remaining.len();
        let total_consumed = headers_len + content_length;

        // Advance the buffer past the consumed data
        self.buffer.advance(total_consumed);

        Ok(Some(Frame {
            content_length,
            content_type,
            content,
        }))
    }

    /// Check if the buffer is empty.
    pub fn is_empty(&self) -> bool {
        self.buffer.is_empty()
    }

    /// Get the current buffer size.
    pub fn buffer_len(&self) -> usize {
        self.buffer.len()
    }

    /// Clear the buffer (e.g., on error recovery).
    pub fn clear(&mut self) {
        self.buffer.clear();
    }
}

/// Encode a message with LSP framing.
///
/// Returns the complete message with Content-Length header.
pub fn encode(content: &str) -> Vec<u8> {
    let header = format!("Content-Length: {}\r\n\r\n", content.len());
    let mut result = Vec::with_capacity(header.len() + content.len());
    result.extend_from_slice(header.as_bytes());
    result.extend_from_slice(content.as_bytes());
    result
}

/// Encode a message with Content-Type header.
pub fn encode_with_content_type(content: &str, content_type: &str) -> Vec<u8> {
    let header = format!(
        "Content-Length: {}\r\nContent-Type: {}\r\n\r\n",
        content.len(),
        content_type
    );
    let mut result = Vec::with_capacity(header.len() + content.len());
    result.extend_from_slice(header.as_bytes());
    result.extend_from_slice(content.as_bytes());
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_message() {
        let msg = b"Content-Length: 13\r\n\r\n{\"test\":true}";
        let mut decoder = Decoder::new();
        decoder.feed(msg);

        let frame = decoder.decode().unwrap().unwrap();
        assert_eq!(frame.content_length, 13);
        assert_eq!(frame.content, "{\"test\":true}");
        assert!(frame.content_type.is_none());
    }

    #[test]
    fn test_with_content_type() {
        let msg = b"Content-Length: 13\r\nContent-Type: application/json\r\n\r\n{\"test\":true}";
        let mut decoder = Decoder::new();
        decoder.feed(msg);

        let frame = decoder.decode().unwrap().unwrap();
        assert_eq!(frame.content_length, 13);
        assert_eq!(frame.content, "{\"test\":true}");
        assert_eq!(frame.content_type, Some("application/json".to_string()));
    }

    #[test]
    fn test_case_insensitive() {
        let msg = b"content-length: 13\r\n\r\n{\"test\":true}";
        let mut decoder = Decoder::new();
        decoder.feed(msg);

        let frame = decoder.decode().unwrap().unwrap();
        assert_eq!(frame.content_length, 13);
    }

    #[test]
    fn test_partial_header() {
        let mut decoder = Decoder::new();
        decoder.feed(b"Content-Length: 13\r\n");

        assert!(decoder.decode().unwrap().is_none());

        decoder.feed(b"\r\n{\"test\":true}");
        let frame = decoder.decode().unwrap().unwrap();
        assert_eq!(frame.content, "{\"test\":true}");
    }

    #[test]
    fn test_partial_content() {
        let mut decoder = Decoder::new();
        decoder.feed(b"Content-Length: 13\r\n\r\n{\"test\":");

        assert!(decoder.decode().unwrap().is_none());

        decoder.feed(b"true}");
        let frame = decoder.decode().unwrap().unwrap();
        assert_eq!(frame.content, "{\"test\":true}");
    }

    #[test]
    fn test_multiple_messages() {
        let msg = b"Content-Length: 2\r\n\r\n{}Content-Length: 4\r\n\r\ntrue";
        let mut decoder = Decoder::new();
        decoder.feed(msg);

        let frame1 = decoder.decode().unwrap().unwrap();
        assert_eq!(frame1.content, "{}");

        let frame2 = decoder.decode().unwrap().unwrap();
        assert_eq!(frame2.content, "true");
    }

    #[test]
    fn test_missing_content_length() {
        let msg = b"Content-Type: application/json\r\n\r\n{}";
        let mut decoder = Decoder::new();
        decoder.feed(msg);

        let result = decoder.decode();
        assert!(matches!(result, Err(FrameError::MissingContentLength)));
    }

    #[test]
    fn test_encode() {
        let encoded = encode("{\"test\":true}");
        assert_eq!(encoded, b"Content-Length: 13\r\n\r\n{\"test\":true}");
    }

    #[test]
    fn test_encode_with_content_type() {
        let encoded = encode_with_content_type("{}", "application/json");
        assert_eq!(
            encoded,
            b"Content-Length: 2\r\nContent-Type: application/json\r\n\r\n{}"
        );
    }

    #[test]
    fn test_content_too_large() {
        let mut decoder = Decoder::with_max_size(10);
        decoder.feed(b"Content-Length: 100\r\n\r\n");

        let result = decoder.decode();
        assert!(matches!(result, Err(FrameError::ContentTooLarge { max: 10 })));
    }
}
