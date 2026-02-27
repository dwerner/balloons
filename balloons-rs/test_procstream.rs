//! Quick test of procstream event streaming

use futures_lite::StreamExt;
use procstream::{Command, Executor, ManagedProcess, Target};

#[smol_potat::main]
async fn main() {
    println!("Testing procstream...");

    let mut cmd = Command::new("sh");
    cmd.arg("-c").arg("echo hello && sleep 0.5 && echo world && sleep 0.5 && echo done");

    let target = Target::ManagedProcess(ManagedProcess::new());
    let executor = Executor::local("test");

    let (mut events, _handle) = executor.launch(&target, cmd).await.expect("launch failed");

    println!("Process launched, waiting for events...");

    while let Some(event) = events.next().await {
        println!("Event: {:?}", event);
    }

    println!("Done!");
}
