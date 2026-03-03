//! LSP protocol support for Content-Length framed JSON-RPC messages.
//!
//! LSP (Language Server Protocol) uses a simple framing format:
//! ```text
//! Content-Length: <length>\r\n
//! \r\n
//! <json-rpc-message>
//! ```
//!
//! This module wraps the `lsp-framing` crate for async reading from process stdout.

use futures_lite::io::{AsyncRead, AsyncReadExt};
use lsp_framing::{Decoder, Frame};
use std::io;

/// An LSP message reader that parses Content-Length framed messages.
///
/// Uses the `lsp-framing` crate's nom-based parser for robust header parsing.
pub struct LspReader<R> {
    inner: R,
    decoder: Decoder,
    read_buf: [u8; 4096],
}

impl<R: AsyncRead + Unpin> LspReader<R> {
    /// Create a new LSP reader wrapping the given reader.
    pub fn new(reader: R) -> Self {
        Self {
            inner: reader,
            decoder: Decoder::new(),
            read_buf: [0u8; 4096],
        }
    }

    /// Create with custom max message size.
    pub fn with_max_size(reader: R, max_size: usize) -> Self {
        Self {
            inner: reader,
            decoder: Decoder::with_max_size(max_size),
            read_buf: [0u8; 4096],
        }
    }

    /// Read the next complete LSP message.
    ///
    /// Returns the JSON content (without headers) or None if EOF.
    pub async fn read_message(&mut self) -> io::Result<Option<String>> {
        loop {
            // Try to decode from existing buffer first
            match self.decoder.decode() {
                Ok(Some(frame)) => return Ok(Some(frame.content)),
                Ok(None) => {
                    // Need more data - read from the underlying reader
                    let n = self.inner.read(&mut self.read_buf).await?;
                    if n == 0 {
                        // EOF - if we have partial data, that's an error
                        if !self.decoder.is_empty() {
                            return Err(io::Error::new(
                                io::ErrorKind::UnexpectedEof,
                                "Unexpected EOF in middle of LSP message",
                            ));
                        }
                        return Ok(None);
                    }
                    self.decoder.feed(&self.read_buf[..n]);
                }
                Err(e) => {
                    return Err(io::Error::new(io::ErrorKind::InvalidData, e.to_string()));
                }
            }
        }
    }

    /// Read the next complete LSP frame (with metadata).
    pub async fn read_frame(&mut self) -> io::Result<Option<Frame>> {
        loop {
            match self.decoder.decode() {
                Ok(Some(frame)) => return Ok(Some(frame)),
                Ok(None) => {
                    let n = self.inner.read(&mut self.read_buf).await?;
                    if n == 0 {
                        if !self.decoder.is_empty() {
                            return Err(io::Error::new(
                                io::ErrorKind::UnexpectedEof,
                                "Unexpected EOF in middle of LSP message",
                            ));
                        }
                        return Ok(None);
                    }
                    self.decoder.feed(&self.read_buf[..n]);
                }
                Err(e) => {
                    return Err(io::Error::new(io::ErrorKind::InvalidData, e.to_string()));
                }
            }
        }
    }
}

/// Format a message with LSP Content-Length header.
pub fn frame_lsp_message(content: &str) -> Vec<u8> {
    lsp_framing::encode(content)
}

/// Format a message with LSP Content-Length header as a String.
pub fn frame_lsp_message_string(content: &str) -> String {
    String::from_utf8(lsp_framing::encode(content)).unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures_lite::io::Cursor;

    #[smol_potat::test]
    async fn test_read_single_message() {
        // {"id":1,"ok":1} is 15 chars
        let input = "Content-Length: 15\r\n\r\n{\"id\":1,\"ok\":1}";
        let cursor = Cursor::new(input.as_bytes());
        let mut reader = LspReader::new(cursor);

        let msg = reader.read_message().await.unwrap().unwrap();
        assert_eq!(msg, "{\"id\":1,\"ok\":1}");
    }

    #[smol_potat::test]
    async fn test_read_multiple_messages() {
        let input = concat!(
            "Content-Length: 15\r\n\r\n{\"id\":1,\"ok\":1}",
            "Content-Length: 15\r\n\r\n{\"id\":2,\"ok\":2}"
        );
        let cursor = Cursor::new(input.as_bytes());
        let mut reader = LspReader::new(cursor);

        let msg1 = reader.read_message().await.unwrap().unwrap();
        assert_eq!(msg1, "{\"id\":1,\"ok\":1}");

        let msg2 = reader.read_message().await.unwrap().unwrap();
        assert_eq!(msg2, "{\"id\":2,\"ok\":2}");

        let msg3 = reader.read_message().await.unwrap();
        assert!(msg3.is_none());
    }

    #[smol_potat::test]
    async fn test_read_with_content_type() {
        let input =
            "Content-Length: 15\r\nContent-Type: application/json\r\n\r\n{\"id\":1,\"ok\":1}";
        let cursor = Cursor::new(input.as_bytes());
        let mut reader = LspReader::new(cursor);

        let msg = reader.read_message().await.unwrap().unwrap();
        assert_eq!(msg, "{\"id\":1,\"ok\":1}");
    }

    #[smol_potat::test]
    async fn test_frame_message() {
        let content = "{\"jsonrpc\":\"2.0\",\"id\":1}";
        let framed = frame_lsp_message_string(content);
        assert_eq!(
            framed,
            "Content-Length: 24\r\n\r\n{\"jsonrpc\":\"2.0\",\"id\":1}"
        );
    }

    #[smol_potat::test]
    async fn test_read_frame_with_metadata() {
        let input =
            "Content-Length: 15\r\nContent-Type: application/json\r\n\r\n{\"id\":1,\"ok\":1}";
        let cursor = Cursor::new(input.as_bytes());
        let mut reader = LspReader::new(cursor);

        let frame = reader.read_frame().await.unwrap().unwrap();
        assert_eq!(frame.content, "{\"id\":1,\"ok\":1}");
        assert_eq!(frame.content_length, 15);
        assert_eq!(frame.content_type, Some("application/json".to_string()));
    }
}
