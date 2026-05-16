//! Browser lifecycle management implementation.
//!
//! Provides functionality to start, stop, and check the status of WebDriver processes.
//!
//! Note: This module does NOT use state files. Each browser instance is independent.
//! The caller is responsible for tracking browser processes (by PID and port).

use std::net::TcpStream;
use std::time::Duration;

use crate::WebDriverSurfer;
use crate::driver::{BrowserConfig, BrowserType};
use crate::error::SurferError;
use crate::runtime::{Command, child_id, child_try_wait, kill_process, sleep};
use crate::state::BrowserState;
use crate::traits::BrowserLifecycle;
use crate::traits::lifecycle::BrowserStatus;

/// Check if WebDriver is ready by testing TCP connection to the port.
/// This is much simpler than creating a full session and doesn't leave orphaned sessions.
fn is_webdriver_port_open(port: u16) -> bool {
    use std::net::ToSocketAddrs;
    let addr = format!("127.0.0.1:{}", port);
    if let Ok(mut addrs) = addr.to_socket_addrs() {
        if let Some(socket_addr) = addrs.next() {
            // Try to connect with a short timeout
            return TcpStream::connect_timeout(&socket_addr, Duration::from_millis(100)).is_ok();
        }
    }
    false
}

/// Find the WebDriver binary for the given browser type.
pub fn find_driver(browser_type: BrowserType) -> Option<String> {
    let binary = browser_type.driver_binary();
    which::which(binary)
        .ok()
        .map(|p| p.to_string_lossy().to_string())
}

/// Start a WebDriver process and wait for it to be ready.
///
/// Returns the `BrowserState` containing the process ID and port.
///
/// Note: No state file is used. The caller tracks browser instances.
/// Each call starts a new driver on the configured port.
pub async fn start_driver(config: &BrowserConfig) -> Result<BrowserState, SurferError> {
    // Find WebDriver
    let driver_path =
        find_driver(config.browser_type).ok_or_else(|| SurferError::BrowserNotFound {
            tried: vec![config.browser_type.driver_binary().to_string()],
        })?;

    // Start WebDriver
    let mut cmd = Command::new(&driver_path);
    let port_arg = format!("--port={}", config.port);
    cmd.arg(&port_arg);
    // Redirect stdout and stderr to null to avoid any blocking
    cmd.stdout_null().stderr_null();

    // Set up X11 environment for non-headless mode
    if !config.headless {
        // Get DISPLAY - try env first, fall back to detecting X0 socket
        let display = std::env::var("DISPLAY").ok().or_else(|| {
            if std::path::Path::new("/tmp/.X11-unix/X0").exists() {
                Some(":0".to_string())
            } else {
                None
            }
        });

        if let Some(display) = display {
            cmd.env("DISPLAY", &display);

            // Get XAUTHORITY - try env first, then common locations
            // Prefer /tmp/xauth_* files (active session) over ~/.Xauthority (may be stale)
            let xauthority = std::env::var("XAUTHORITY").ok().or_else(|| {
                // Try /tmp/xauth_* files first (typically the active X session)
                if let Ok(entries) = std::fs::read_dir("/tmp") {
                    for entry in entries.flatten() {
                        let name = entry.file_name();
                        let name_str = name.to_string_lossy();
                        if name_str.starts_with("xauth_") {
                            return Some(entry.path().to_string_lossy().to_string());
                        }
                    }
                }
                // Fall back to ~/.Xauthority
                if let Some(home) = std::env::var("HOME").ok() {
                    let home_xauth = format!("{home}/.Xauthority");
                    if std::path::Path::new(&home_xauth).exists() {
                        return Some(home_xauth);
                    }
                }
                None
            });

            if let Some(xauth) = xauthority {
                cmd.env("XAUTHORITY", &xauth);
            }
        }
    }

    let mut child = cmd
        .spawn()
        .map_err(|e| SurferError::BrowserStartFailed(format!("spawn failed: {}", e)))?;

    let pid = child_id(&child).unwrap_or(0);

    // Give the driver a moment to start
    sleep(Duration::from_millis(500)).await;

    // Check if process exited immediately (crashed) using try_wait which is reliable
    if let Ok(Some(status)) = child_try_wait(&mut child) {
        return Err(SurferError::BrowserStartFailed(format!(
            "WebDriver process (pid {}) exited immediately with {:?}",
            pid, status
        )));
    }

    // Wait for WebDriver to be ready
    let mut connected = false;
    let mut last_error: Option<String> = None;

    for _attempt in 0..30 {
        sleep(Duration::from_millis(200)).await;

        // Check if process is still alive using try_wait
        if let Ok(Some(status)) = child_try_wait(&mut child) {
            return Err(SurferError::BrowserStartFailed(format!(
                "WebDriver process (pid {}) died during startup ({:?})",
                pid, status
            )));
        }

        // Check if WebDriver port is open (simple TCP check, no session creation)
        if is_webdriver_port_open(config.port) {
            connected = true;
            break;
        } else {
            last_error = Some(format!("Port {} not open", config.port));
        }
    }

    if !connected {
        // Kill the driver process
        let _ = kill_process(pid);

        let conn_error = last_error.unwrap_or_else(|| "unknown".to_string());
        return Err(SurferError::BrowserStartFailed(format!(
            "WebDriver started but connection failed (pid {}): {}",
            pid, conn_error
        )));
    }

    // Return state (no file persistence - caller tracks instances)
    let state = BrowserState::new(pid, config.port, config.browser_type, config.headless);
    Ok(state)
}

/// Stop a WebDriver process by PID.
///
/// Note: The caller must provide the PID (from the BrowserState returned by start_driver).
pub fn stop_driver_by_pid(pid: u32) -> Result<(), SurferError> {
    kill_process(pid).map_err(|e| SurferError::BrowserStopFailed(e.to_string()))
}

/// Check if a process is still running.
pub fn is_driver_running(pid: u32) -> bool {
    // Check if process exists by sending signal 0
    #[cfg(unix)]
    {
        unsafe { libc::kill(pid as i32, 0) == 0 }
    }
    #[cfg(not(unix))]
    {
        // Fallback for non-unix - assume running
        true
    }
}

/// Get the status of a WebDriver process by PID and port.
pub fn driver_status_by_pid(pid: u32, port: u16) -> BrowserStatus {
    if is_driver_running(pid) {
        BrowserStatus::Running { pid, port }
    } else {
        BrowserStatus::NotRunning
    }
}

// Implement BrowserLifecycle for WebDriverSurfer
use async_trait::async_trait;

#[async_trait]
impl BrowserLifecycle for WebDriverSurfer {
    async fn start(config: &BrowserConfig) -> Result<BrowserState, SurferError> {
        start_driver(config).await
    }

    async fn stop() -> Result<(), SurferError> {
        // Legacy method - can't stop without knowing PID
        // Callers should use stop_driver_by_pid() instead
        Err(SurferError::BrowserStopFailed(
            "Use stop_driver_by_pid() with the browser's PID".to_string(),
        ))
    }

    async fn status() -> Result<BrowserStatus, SurferError> {
        // Legacy method - can't check status without knowing PID
        // Callers should use driver_status_by_pid() instead
        Ok(BrowserStatus::NotRunning)
    }
}
