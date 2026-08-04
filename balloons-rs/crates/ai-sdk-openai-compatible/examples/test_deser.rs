fn main() {
    // Test 1: Full JSON with escaped quotes
    let json1 = r#"{"name":"Bash","arguments":"{\"command\":\"ls\"}"}"#;
    #[derive(serde::Deserialize, Debug)]
    struct Test1 { name: Option<String>, arguments: Option<String> }
    let parsed1: Test1 = serde_json::from_str(json1).unwrap();
    println!("Test 1: {:?}", parsed1);
    
    // Test 2: Just the arguments part - escaped quote, command, escaped quote, colon, escaped quote
    let json2 = r#"{"arguments":"\"command\":\""}"#;
    #[derive(serde::Deserialize, Debug)]
    struct Test2 { arguments: Option<String> }
    let parsed2: Test2 = serde_json::from_str(json2).unwrap();
    println!("Test 2: {:?}", parsed2);
    
    // Test 3: arguments with ls
    let json3 = r#"{"arguments":"ls"}"#;
    #[derive(serde::Deserialize, Debug)]
    struct Test3 { arguments: Option<String> }
    let parsed3: Test3 = serde_json::from_str(json3).unwrap();
    println!("Test 3: {:?}", parsed3);
}
