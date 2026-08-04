use futures::StreamExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let response = reqwest::get("https://httpbin.org/stream/5").await?;
    let stream = response.bytes_stream();
    let event_stream = eventsource_stream::EventStream::new(stream);
    
    tokio::pin!(event_stream);
    
    while let Some(event) = event_stream.next().await {
        println!("Event: {:?}", event);
    }
    
    Ok(())
}
