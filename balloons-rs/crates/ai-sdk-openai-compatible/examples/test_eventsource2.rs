use futures::StreamExt;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let response = reqwest::get("https://httpbin.org/stream/5").await?;
    let stream = response.bytes_stream();
    let event_stream = eventsource_stream::EventStream::new(stream);
    
    tokio::pin!(event_stream);
    
    while let Some(result) = event_stream.next().await {
        match result {
            Ok(event) => {
                println!("Event: data={:?}, event={:?}, id={:?}", 
                    event.data.chars().take(50).collect::<String>(), 
                    event.event, 
                    event.id);
            }
            Err(e) => {
                println!("Error: {:?}", e);
                break;
            }
        }
    }
    
    Ok(())
}
