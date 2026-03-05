use async_channel::{Sender, unbounded};
use pyo3::prelude::*;
use std::sync::Arc;
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};

/// A more accurate simulation of fantoccini's Session - implements Future manually
struct Session {
    rx: async_channel::Receiver<(String, async_channel::Sender<String>)>,
}

impl Unpin for Session {}

impl Session {
    fn new(rx: async_channel::Receiver<(String, async_channel::Sender<String>)>) -> Self {
        Self { rx }
    }
}

impl Future for Session {
    type Output = ();

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        eprintln!("[test] Session::poll called on thread {:?}", std::thread::current().id());

        loop {
            let recv_fut = this.rx.recv();
            let mut recv_fut = std::pin::pin!(recv_fut);

            match recv_fut.as_mut().poll(cx) {
                Poll::Ready(Ok((msg, reply_tx))) => {
                    eprintln!("[test] Session received: {}", msg);
                    // Send response back
                    let response = format!("Response to: {}", msg);
                    let _ = reply_tx.try_send(response);
                }
                Poll::Ready(Err(_)) => {
                    eprintln!("[test] Session: channel closed");
                    return Poll::Ready(());
                }
                Poll::Pending => {
                    eprintln!("[test] Session: recv() returned Pending, rx.len()={}", this.rx.len());
                    return Poll::Pending;
                }
            }
        }
    }
}

/// Mimics fantoccini's Client
#[pyclass]
struct Client {
    tx: Sender<(String, async_channel::Sender<String>)>,
    _session_handle: Arc<smol::Task<()>>,
}

async fn setup_session() -> Client {
    let (tx, rx) = unbounded::<(String, async_channel::Sender<String>)>();

    eprintln!("[test] setup_session: spawning Session task with smol::spawn");

    let session_handle = smol::spawn(async move {
        eprintln!("[test] Session task started on thread {:?}", std::thread::current().id());
        Session::new(rx).await;
        eprintln!("[test] Session task ended");
    });

    Client {
        tx,
        _session_handle: Arc::new(session_handle),
    }
}

async fn connect_with_initial_command() -> Client {
    let client = setup_session().await;

    // Send initial command and wait for response
    let (reply_tx, reply_rx) = unbounded::<String>();
    eprintln!("[test] connect: sending initial command");
    client.tx.send(("INIT".to_string(), reply_tx)).await.unwrap();

    // Wait for response (like fantoccini waits for NewSession response)
    eprintln!("[test] connect: waiting for response");
    let response = reply_rx.recv().await.unwrap();
    eprintln!("[test] connect: got response: {}", response);

    client
}

async fn check_driver_ready() -> bool {
    eprintln!("[test] check_driver_ready: creating throwaway client...");
    let throwaway = connect_with_initial_command().await;
    eprintln!("[test] check_driver_ready: got client, now dropping it");
    drop(throwaway);
    eprintln!("[test] check_driver_ready: done");
    true
}

#[pymethods]
impl Client {
    #[staticmethod]
    fn connect<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        eprintln!("[test] Client::connect called from Python");

        pyo3_async_runtimes::smol::future_into_py(py, async move {
            check_driver_ready().await;
            let client = connect_with_initial_command().await;
            eprintln!("[test] Client::connect completed");
            Ok(client)
        })
    }

    /// Send a message AND WAIT FOR RESPONSE - this is like fantoccini's issue()
    fn send<'py>(&self, py: Python<'py>, msg: String) -> PyResult<Bound<'py, PyAny>> {
        let tx = self.tx.clone();
        eprintln!("[test] send() called, msg={}, senders={}, receivers={}",
            msg, tx.sender_count(), tx.receiver_count());

        pyo3_async_runtimes::smol::future_into_py(py, async move {
            let (reply_tx, reply_rx) = unbounded::<String>();

            eprintln!("[test] send future: sending message");
            tx.send((msg, reply_tx)).await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!("Send failed: {}", e))
            })?;

            eprintln!("[test] send future: waiting for response");
            let response = reply_rx.recv().await.map_err(|e| {
                pyo3::exceptions::PyRuntimeError::new_err(format!("Recv failed: {}", e))
            })?;
            eprintln!("[test] send future: got response: {}", response);

            Ok(response)
        })
    }
}

#[pymodule]
fn test_smol_channel(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Client>()?;
    Ok(())
}
