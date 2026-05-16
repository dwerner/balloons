//! Runtime abstraction for async operations.
//!
//! Surfer now uses a smol-based runtime internally.

use std::future::Future;
use std::time::Duration;

/// Sleep for the specified duration.
pub async fn sleep(duration: Duration) {
    smol::Timer::after(duration).await;
}

/// Spawn a future on the runtime.
pub fn spawn<F, T>(future: F)
where
    F: Future<Output = T> + Send + 'static,
    T: Send + 'static,
{
    smol::spawn(future).detach();
}

/// Run a blocking operation.
pub async fn spawn_blocking<F, T>(f: F) -> T
where
    F: FnOnce() -> T + Send + 'static,
    T: Send + 'static,
{
    smol::unblock(f).await
}

/// Process handle abstraction.
pub type Child = async_process::Child;

/// Command builder abstraction.
pub struct Command {
    inner: async_process::Command,
}

impl Command {
    /// Create a new command.
    pub fn new(program: &str) -> Self {
        let mut cmd = async_process::Command::new(program);
        // Don't kill the child when the Child handle is dropped.
        cmd.kill_on_drop(false);
        Self { inner: cmd }
    }

    /// Add an argument.
    pub fn arg(&mut self, arg: &str) -> &mut Self {
        self.inner.arg(arg);
        self
    }

    /// Add multiple arguments.
    pub fn args<I, S>(&mut self, args: I) -> &mut Self
    where
        I: IntoIterator<Item = S>,
        S: AsRef<std::ffi::OsStr>,
    {
        self.inner.args(args);
        self
    }

    /// Set stdout to null.
    pub fn stdout_null(&mut self) -> &mut Self {
        self.inner.stdout(std::process::Stdio::null());
        self
    }

    /// Set stderr to null.
    pub fn stderr_null(&mut self) -> &mut Self {
        self.inner.stderr(std::process::Stdio::null());
        self
    }

    /// Capture stderr (piped).
    pub fn stderr_piped(&mut self) -> &mut Self {
        self.inner.stderr(std::process::Stdio::piped());
        self
    }

    /// Set an environment variable.
    pub fn env(&mut self, key: &str, val: &str) -> &mut Self {
        self.inner.env(key, val);
        self
    }

    /// Spawn the command.
    pub fn spawn(&mut self) -> std::io::Result<Child> {
        self.inner.spawn()
    }
}

/// Read stderr from child process (non-blocking, returns what's available).
pub async fn read_child_stderr(child: &mut Child) -> Option<String> {
    use futures::io::AsyncReadExt;
    if let Some(stderr) = child.stderr.as_mut() {
        let mut buf = Vec::new();
        match smol_timeout::TimeoutExt::timeout(
            stderr.read_to_end(&mut buf),
            Duration::from_millis(100),
        )
        .await
        {
            Some(Ok(_)) => Some(String::from_utf8_lossy(&buf).to_string()),
            _ => None,
        }
    } else {
        None
    }
}

/// Get the process ID from a child process.
pub fn child_id(child: &Child) -> Option<u32> {
    Some(child.id())
}

/// Check if child process has exited. Returns Some(exit_code) if exited, None if still running.
pub fn child_try_wait(child: &mut Child) -> std::io::Result<Option<std::process::ExitStatus>> {
    child.try_status()
}

/// Kill a process by PID.
#[cfg(unix)]
pub fn kill_process(pid: u32) -> std::io::Result<()> {
    use std::io::Error;

    let result = unsafe { libc::kill(pid as i32, libc::SIGTERM) };

    if result == 0 {
        Ok(())
    } else {
        Err(Error::last_os_error())
    }
}

#[cfg(not(unix))]
pub fn kill_process(_pid: u32) -> std::io::Result<()> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "kill not supported on this platform",
    ))
}
