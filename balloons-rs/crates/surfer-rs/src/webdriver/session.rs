//! WebDriver session management using smol runtime.

use crate::webdriver::cookies::AddCookieParametersWrapper;
use crate::webdriver::error::ErrorStatus;
use crate::webdriver::http::{RequestData, ResponseData};
use crate::webdriver::wd::{self, WebDriverCompatibleCommand};
use crate::webdriver::{Client, error};
use base64::Engine;
use http::header::{AUTHORIZATION, CONTENT_TYPE, USER_AGENT};
use isahc::{AsyncReadResponseExt, HttpClient, Request};
use serde_json::Value as Json;
use std::io;
use webdriver::command::WebDriverCommand;
use webdriver::response::NewSessionResponse;

use async_channel::Receiver;
pub use futures_channel::oneshot;

type Ack = oneshot::Sender<Result<Json, error::CmdError>>;
type Wcmd = WebDriverCommand<webdriver::command::VoidWebDriverExtensionCommand>;

#[allow(clippy::large_enum_variant)]
pub(crate) enum Cmd {
    SetUa(String),
    GetSessionId,
    Shutdown,
    Persist,
    GetUa,
    Raw {
        req: RequestData,
        rsp: oneshot::Sender<Result<ResponseData, error::CmdError>>,
    },
    WebDriver(Box<dyn WebDriverCompatibleCommand + Send>),
}

impl std::fmt::Debug for Cmd {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Cmd::SetUa(ua) => f.debug_tuple("SetUa").field(ua).finish(),
            Cmd::GetSessionId => f.write_str("GetSessionId"),
            Cmd::Shutdown => f.write_str("Shutdown"),
            Cmd::Persist => f.write_str("Persist"),
            Cmd::GetUa => f.write_str("GetUa"),
            Cmd::Raw { .. } => f.write_str("Raw { .. }"),
            Cmd::WebDriver(cmd) => f.debug_tuple("WebDriver").field(cmd).finish(),
        }
    }
}

impl WebDriverCompatibleCommand for Wcmd {
    fn endpoint(
        &self,
        base_url: &url::Url,
        session_id: Option<&str>,
    ) -> Result<url::Url, url::ParseError> {
        if let WebDriverCommand::NewSession(..) = self {
            return base_url.join("session");
        }
        if let WebDriverCommand::Status = self {
            return base_url.join("status");
        }

        let base = base_url.join(&format!("session/{}/", session_id.as_ref().unwrap()))?;
        match self {
            WebDriverCommand::NewSession(..) => unreachable!(),
            WebDriverCommand::DeleteSession => unreachable!(),
            WebDriverCommand::Get(..) | WebDriverCommand::GetCurrentUrl => base.join("url"),
            WebDriverCommand::GoBack => base.join("back"),
            WebDriverCommand::GoForward => base.join("forward"),
            WebDriverCommand::Refresh => base.join("refresh"),
            WebDriverCommand::GetTitle => base.join("title"),
            WebDriverCommand::GetPageSource => base.join("source"),
            WebDriverCommand::GetWindowHandle => base.join("window"),
            WebDriverCommand::GetWindowHandles => base.join("window/handles"),
            WebDriverCommand::NewWindow(..) => base.join("window/new"),
            WebDriverCommand::CloseWindow => base.join("window"),
            WebDriverCommand::GetWindowRect => base.join("window/rect"),
            WebDriverCommand::SetWindowRect(..) => base.join("window/rect"),
            WebDriverCommand::MinimizeWindow => base.join("window/minimize"),
            WebDriverCommand::MaximizeWindow => base.join("window/maximize"),
            WebDriverCommand::FullscreenWindow => base.join("window/fullscreen"),
            WebDriverCommand::SwitchToWindow(..) => base.join("window"),
            WebDriverCommand::SwitchToFrame(_) => base.join("frame"),
            WebDriverCommand::SwitchToParentFrame => base.join("frame/parent"),
            WebDriverCommand::FindElement(..) => base.join("element"),
            WebDriverCommand::FindElements(..) => base.join("elements"),
            WebDriverCommand::FindElementElement(p, _) => {
                base.join(&format!("element/{}/element", p.0))
            }
            WebDriverCommand::FindElementElements(p, _) => {
                base.join(&format!("element/{}/elements", p.0))
            }
            WebDriverCommand::GetActiveElement => base.join("element/active"),
            WebDriverCommand::IsDisplayed(we) => base.join(&format!("element/{}/displayed", we.0)),
            WebDriverCommand::IsSelected(we) => base.join(&format!("element/{}/selected", we.0)),
            WebDriverCommand::GetElementAttribute(we, attr) => {
                base.join(&format!("element/{}/attribute/{}", we.0, attr))
            }
            WebDriverCommand::GetElementProperty(we, prop) => {
                base.join(&format!("element/{}/property/{}", we.0, prop))
            }
            WebDriverCommand::GetCSSValue(we, attr) => {
                base.join(&format!("element/{}/css/{}", we.0, attr))
            }
            WebDriverCommand::GetElementText(we) => base.join(&format!("element/{}/text", we.0)),
            WebDriverCommand::GetElementTagName(we) => base.join(&format!("element/{}/name", we.0)),
            WebDriverCommand::GetElementRect(we) => base.join(&format!("element/{}/rect", we.0)),
            WebDriverCommand::IsEnabled(we) => base.join(&format!("element/{}/enabled", we.0)),
            WebDriverCommand::ExecuteScript(..) => base.join("execute/sync"),
            WebDriverCommand::ExecuteAsyncScript(..) => base.join("execute/async"),
            WebDriverCommand::GetCookies
            | WebDriverCommand::AddCookie(_)
            | WebDriverCommand::DeleteCookies => base.join("cookie"),
            WebDriverCommand::GetNamedCookie(name) | WebDriverCommand::DeleteCookie(name) => {
                base.join(&format!("cookie/{}", name))
            }
            WebDriverCommand::GetTimeouts | WebDriverCommand::SetTimeouts(..) => {
                base.join("timeouts")
            }
            WebDriverCommand::ElementClick(we) => base.join(&format!("element/{}/click", we.0)),
            WebDriverCommand::ElementClear(we) => base.join(&format!("element/{}/clear", we.0)),
            WebDriverCommand::ElementSendKeys(we, _) => {
                base.join(&format!("element/{}/value", we.0))
            }
            WebDriverCommand::PerformActions(..) | WebDriverCommand::ReleaseActions => {
                base.join("actions")
            }
            WebDriverCommand::DismissAlert => base.join("alert/dismiss"),
            WebDriverCommand::AcceptAlert => base.join("alert/accept"),
            WebDriverCommand::GetAlertText | WebDriverCommand::SendAlertText(..) => {
                base.join("alert/text")
            }
            WebDriverCommand::TakeScreenshot => base.join("screenshot"),
            WebDriverCommand::TakeElementScreenshot(we) => {
                base.join(&format!("element/{}/screenshot", we.0))
            }
            WebDriverCommand::Print(..) => base.join("print"),
            WebDriverCommand::Status => unreachable!(),
            _ => unimplemented!(),
        }
    }

    fn method_and_body(&self, request_url: &url::Url) -> (http::Method, Option<String>) {
        use http::Method;
        use webdriver::command;
        let mut method = Method::GET;
        let mut body = None;
        match self {
            WebDriverCommand::NewSession(command::NewSessionParameters { capabilities: conf }) => {
                let mut capabilities = serde_json::value::Map::new();
                capabilities.insert("capabilities".into(), serde_json::to_value(conf).unwrap());
                if !request_url.username().is_empty() {
                    capabilities.insert(
                        "user".into(),
                        serde_json::to_value(request_url.username()).unwrap(),
                    );
                }
                if let Some(pwd) = request_url.password() {
                    capabilities.insert("user".into(), serde_json::to_value(pwd).unwrap());
                }
                body =
                    Some(serde_json::to_string(&serde_json::Value::Object(capabilities)).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::Get(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::FindElement(loc)
            | WebDriverCommand::FindElements(loc)
            | WebDriverCommand::FindElementElement(_, loc)
            | WebDriverCommand::FindElementElements(_, loc) => {
                body = Some(serde_json::to_string(loc).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::ExecuteScript(script)
            | WebDriverCommand::ExecuteAsyncScript(script) => {
                body = Some(serde_json::to_string(script).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::ElementSendKeys(_, keys) => {
                body = Some(serde_json::to_string(keys).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::ElementClick(..)
            | WebDriverCommand::ElementClear(..)
            | WebDriverCommand::GoBack
            | WebDriverCommand::GoForward
            | WebDriverCommand::Refresh
            | WebDriverCommand::MinimizeWindow
            | WebDriverCommand::MaximizeWindow
            | WebDriverCommand::FullscreenWindow
            | WebDriverCommand::DismissAlert
            | WebDriverCommand::AcceptAlert
            | WebDriverCommand::SwitchToParentFrame => {
                body = Some("{}".to_string());
                method = Method::POST;
            }
            WebDriverCommand::NewWindow(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::SetWindowRect(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::SwitchToWindow(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::SwitchToFrame(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::SetTimeouts(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::PerformActions(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::SendAlertText(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::Print(params) => {
                body = Some(serde_json::to_string(params).unwrap());
                method = Method::POST;
            }
            WebDriverCommand::AddCookie(params) => {
                body = Some(
                    serde_json::to_string(&AddCookieParametersWrapper { cookie: params }).unwrap(),
                );
                method = Method::POST;
            }
            WebDriverCommand::CloseWindow
            | WebDriverCommand::DeleteCookie(_)
            | WebDriverCommand::DeleteCookies
            | WebDriverCommand::ReleaseActions => {
                method = Method::DELETE;
            }
            _ => {}
        }
        (method, body)
    }

    fn is_new_session(&self) -> bool {
        matches!(self, WebDriverCommand::NewSession(..))
    }
}

impl From<Wcmd> for Cmd {
    fn from(o: Wcmd) -> Self {
        Cmd::WebDriver(Box::new(o))
    }
}

pub(crate) struct Task {
    pub(crate) request: Cmd,
    pub(crate) ack: Ack,
}

impl std::fmt::Debug for Task {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Task")
            .field("request", &self.request)
            .field("ack", &"<oneshot::Sender>")
            .finish()
    }
}

impl Client {
    pub(crate) async fn issue<C>(&self, cmd: C) -> Result<Json, error::CmdError>
    where
        C: Into<Cmd>,
    {
        let (tx, rx) = oneshot::channel();
        if self
            .tx
            .send(Task {
                request: cmd.into(),
                ack: tx,
            })
            .await
            .is_err()
        {
            return Err(error::CmdError::Lost(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "WebDriver session has been closed",
            )));
        }
        match rx.await {
            Ok(result) => result,
            Err(_) => Err(error::CmdError::Lost(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "WebDriver session was closed while waiting",
            ))),
        }
    }

    /// Issue a WebDriver-compatible command directly to the active session.
    pub async fn issue_cmd(
        &self,
        cmd: impl WebDriverCompatibleCommand + Send + 'static,
    ) -> Result<Json, error::CmdError> {
        self.issue(Cmd::WebDriver(Box::new(cmd))).await
    }
}

pub(crate) struct Session {
    rx: Receiver<Task>,
    client: HttpClient,
    wdb: url::Url,
    session: Option<String>,
    ua: Option<String>,
    persist: bool,
}

impl Session {
    fn new(
        rx: Receiver<Task>,
        client: HttpClient,
        wdb_url: url::Url,
        session_id: Option<impl Into<String>>,
    ) -> Self {
        Self {
            rx,
            client,
            wdb: wdb_url,
            session: session_id.map(Into::into),
            ua: None,
            persist: false,
        }
    }

    async fn run(mut self) {
        while let Ok(Task { request, ack }) = self.rx.recv().await {
            match request {
                Cmd::GetSessionId => {
                    let _ = ack.send(Ok(self
                        .session
                        .clone()
                        .map(Json::String)
                        .unwrap_or(Json::Null)));
                }
                Cmd::SetUa(ua) => {
                    self.ua = Some(ua);
                    let _ = ack.send(Ok(Json::Null));
                }
                Cmd::GetUa => {
                    let _ = ack.send(Ok(self.ua.clone().map(Json::String).unwrap_or(Json::Null)));
                }
                Cmd::Persist => {
                    self.persist = true;
                    let _ = ack.send(Ok(Json::Null));
                }
                Cmd::Shutdown => {
                    if let Some(ref session_id) = self.session {
                        let url = self.wdb.join(&format!("session/{}", session_id)).unwrap();
                        let _ = self
                            .execute_request(RequestData {
                                method: http::Method::DELETE,
                                url: url.to_string(),
                                headers: http::HeaderMap::new(),
                                body: Vec::new(),
                            })
                            .await;
                    }
                    let _ = ack.send(Ok(Json::Null));
                    break;
                }
                Cmd::Raw { req, rsp } => {
                    let result = self.execute_request(req).await;
                    let _ = ack.send(Ok(Json::Null));
                    let _ = rsp.send(result);
                }
                Cmd::WebDriver(cmd) => {
                    let try_extract_session = self.session.is_none();
                    let result = self.issue_wd_cmd(cmd).await;
                    if try_extract_session {
                        if let Ok(Json::Object(ref v)) = result {
                            if let Some(session_id) = v.get("sessionId").and_then(|v| v.as_str()) {
                                self.session = Some(session_id.to_string());
                            }
                        }
                    }
                    let _ = ack.send(result);
                }
            }
        }
        if !self.persist {
            if let Some(ref session_id) = self.session {
                let url = self.wdb.join(&format!("session/{}", session_id)).unwrap();
                let _ = self
                    .execute_request(RequestData {
                        method: http::Method::DELETE,
                        url: url.to_string(),
                        headers: http::HeaderMap::new(),
                        body: Vec::new(),
                    })
                    .await;
            }
        }
    }

    async fn execute_request(&self, req: RequestData) -> Result<ResponseData, error::CmdError> {
        let mut builder = Request::builder().method(req.method).uri(req.url);
        for (k, v) in req.headers.iter() {
            builder = builder.header(k, v);
        }
        let request = builder
            .body(req.body)
            .map_err(|e| error::CmdError::NotJson(e.to_string()))?;
        let mut response = self
            .client
            .send_async(request)
            .await
            .map_err(error::CmdError::from)?;
        let status = response.status();
        let headers = response.headers().clone();
        let body = response
            .bytes()
            .await
            .map_err(error::CmdError::from)?
            .to_vec();
        Ok(ResponseData {
            status,
            headers,
            body,
        })
    }

    fn map_handshake_response(
        response: Result<Json, error::CmdError>,
    ) -> Result<NewSessionResponse, error::NewSessionError> {
        match response {
            Ok(Json::Object(v)) => {
                if let (Some(Json::String(session_id)), Some(capabilities)) =
                    (v.get("sessionId"), v.get("capabilities"))
                {
                    if capabilities.is_object() {
                        return Ok(NewSessionResponse {
                            session_id: session_id.to_owned(),
                            capabilities: capabilities.to_owned(),
                        });
                    }
                }
                Err(error::NewSessionError::NotW3C(Json::Object(v)))
            }
            Ok(v) | Err(error::CmdError::NotW3C(v)) => Err(error::NewSessionError::NotW3C(v)),
            Err(error::CmdError::Failed(e)) => Err(error::NewSessionError::Failed(e)),
            Err(error::CmdError::Lost(e)) => Err(error::NewSessionError::Lost(e)),
            Err(error::CmdError::NotJson(v)) => {
                Err(error::NewSessionError::NotW3C(Json::String(v)))
            }
            Err(error::CmdError::Standard(
                e @ error::WebDriver {
                    error: ErrorStatus::SessionNotCreated,
                    ..
                },
            )) => Err(error::NewSessionError::SessionNotCreated(e)),
            Err(error::CmdError::Standard(
                e @ error::WebDriver {
                    error: ErrorStatus::UnknownError,
                    ..
                },
            )) => Err(error::NewSessionError::NotW3C(
                serde_json::to_value(e).unwrap(),
            )),
            Err(e) => Err(error::NewSessionError::UnexpectedError(e)),
        }
    }

    pub(crate) async fn create_client_and_parse_url(
        webdriver: &str,
    ) -> Result<(HttpClient, url::Url), error::NewSessionError> {
        let wdb = webdriver
            .parse::<url::Url>()
            .map_err(error::NewSessionError::BadWebdriverUrl)?;
        let client = HttpClient::new().map_err(error::NewSessionError::Failed)?;
        Ok((client, wdb))
    }

    pub(crate) async fn setup_session(
        client: HttpClient,
        wdb: url::Url,
        session_id: Option<&str>,
    ) -> Result<Client, error::NewSessionError> {
        let (tx, rx) = async_channel::unbounded();
        let session_id_owned = session_id.map(|id| id.to_string());
        let session_handle = std::thread::spawn(move || {
            smol::block_on(async move {
                Session::new(rx, client, wdb, session_id_owned).run().await;
            });
        });
        Ok(Client {
            tx,
            new_session_response: None,
            _session_handle: std::sync::Arc::new(session_handle),
        })
    }

    pub(crate) async fn with_capabilities(
        webdriver: &str,
        cap: &webdriver::capabilities::Capabilities,
    ) -> Result<Client, error::NewSessionError> {
        let (client, wdb) = Self::create_client_and_parse_url(webdriver).await?;
        let mut cap = cap.to_owned();
        if !cap.contains_key("pageLoadStrategy") {
            cap.insert("pageLoadStrategy".to_string(), Json::from("normal"));
        }
        if cap.get("browserName") != Some(&Json::from("internet explorer")) {
            cap.entry("goog:chromeOptions".to_string())
                .or_insert_with(|| Json::Object(serde_json::Map::new()))
                .as_object_mut()
                .unwrap()
                .insert("w3c".to_string(), Json::from(true));
        }
        let mut client = Self::setup_session(client, wdb, None).await?;
        let session_config = webdriver::capabilities::SpecNewSessionParameters {
            alwaysMatch: cap.clone(),
            firstMatch: vec![webdriver::capabilities::Capabilities::new()],
        };
        let spec = webdriver::command::NewSessionParameters {
            capabilities: session_config,
        };
        match Self::map_handshake_response(client.issue(WebDriverCommand::NewSession(spec)).await) {
            Ok(new_session_response) => {
                client.new_session_response =
                    Some(wd::NewSessionResponse::from_wd(new_session_response));
                Ok(client)
            }
            Err(e) => Err(e),
        }
    }

    async fn issue_wd_cmd(
        &self,
        cmd: Box<impl WebDriverCompatibleCommand + Send + 'static + ?Sized>,
    ) -> Result<Json, error::CmdError> {
        let url = cmd
            .endpoint(&self.wdb, self.session.as_deref())
            .map_err(error::CmdError::from)?;
        let (method, body) = cmd.method_and_body(&url);
        let mut headers = http::HeaderMap::new();
        if let Some(ref s) = self.ua {
            headers.insert(USER_AGENT, s.parse().unwrap());
        }
        if !url.username().is_empty() || url.password().is_some() {
            headers.insert(
                AUTHORIZATION,
                format!(
                    "Basic {}",
                    base64::engine::general_purpose::STANDARD.encode(format!(
                        "{}:{}",
                        url.username(),
                        url.password().unwrap_or("")
                    ))
                )
                .parse()
                .unwrap(),
            );
        }
        let body_bytes = if let Some(body) = body {
            headers.insert(
                CONTENT_TYPE,
                "application/json; charset=utf-8".parse().unwrap(),
            );
            body.into_bytes()
        } else {
            Vec::new()
        };
        let res = self
            .execute_request(RequestData {
                method,
                url: url.to_string(),
                headers,
                body: body_bytes,
            })
            .await?;
        let ctype = res
            .headers
            .get(CONTENT_TYPE)
            .and_then(|ctype| ctype.to_str().ok()?.parse::<mime::Mime>().ok());
        let body = String::from_utf8(res.body).expect("non utf-8 response from webdriver");
        if let Some(ctype) = ctype {
            if !(ctype.type_() == mime::APPLICATION_JSON.type_()
                && ctype.subtype() == mime::APPLICATION_JSON.subtype())
            {
                return Err(error::CmdError::NotJson(body));
            }
        } else {
            return Err(error::CmdError::NotJson(body));
        }
        let is_success = res.status.is_success();
        let body = match serde_json::from_str(&body)? {
            Json::Object(mut v) => v
                .remove("value")
                .ok_or(error::CmdError::NotW3C(Json::Object(v))),
            v => Err(error::CmdError::NotW3C(v)),
        }?;
        if is_success {
            return Ok(body);
        }
        let mut body = match body {
            Json::Object(o) => o,
            j => return Err(error::CmdError::NotW3C(j)),
        };
        body.remove("screen");
        if !body.contains_key("error")
            || !body.contains_key("message")
            || !body["error"].is_string()
            || !body["message"].is_string()
        {
            return Err(error::CmdError::NotW3C(Json::Object(body)));
        }
        let es = body["error"].as_str().unwrap().parse()?;
        let message = match body.remove("message") {
            Some(Json::String(x)) => x,
            _ => String::new(),
        };
        let mut wd_error = error::WebDriver::new(es, message);
        if let Some(Json::String(x)) = body.remove("stacktrace") {
            wd_error = wd_error.with_stacktrace(x);
        }
        if let Some(x) = body.remove("data") {
            wd_error = wd_error.with_data(x);
        }
        Err(error::CmdError::from_webdriver_error(wd_error))
    }
}
