#![allow(rustdoc::private_doc_tests)]

use crate::webdriver::wd::Capabilities;

macro_rules! via_json {
    ($x:expr) => {{ serde_json::from_str(&serde_json::to_string($x).unwrap()).unwrap() }};
}

pub mod error;
pub mod http;
mod session;

#[derive(Default, Clone, Debug)]
pub struct ClientBuilder<C> {
    capabilities: Option<Capabilities>,
    _connector: std::marker::PhantomData<C>,
}

impl ClientBuilder<()> {
    pub fn smol() -> Self {
        Self::new(())
    }
}

impl<C> ClientBuilder<C> {
    pub fn new(connector: C) -> Self {
        let _ = connector;
        Self {
            capabilities: None,
            _connector: std::marker::PhantomData,
        }
    }

    pub fn capabilities(&mut self, cap: Capabilities) -> &mut Self {
        self.capabilities = Some(cap);
        self
    }

    pub async fn connect(&self, webdriver: &str) -> Result<Client, error::NewSessionError> {
        if let Some(ref cap) = self.capabilities {
            Client::with_capabilities_and_connector(webdriver, cap).await
        } else {
            Client::new_with_connector(webdriver).await
        }
    }
}

pub mod client;
pub use client::Client;

pub mod actions;
pub mod cookies;
pub mod elements;
pub mod key;
pub mod wait;
pub mod wd;
pub use wd::Locator;
mod print;
