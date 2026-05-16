# Surfer

Async browser automation crate for Rust with runtime agnosticism.

## Requirements

Surfer uses the WebDriver protocol, which requires:

1. **A browser** installed on your system:
   - Firefox, or
   - Chrome/Chromium

2. **The corresponding WebDriver binary** in your PATH:
   - `geckodriver` for Firefox
   - `chromedriver` for Chrome

### Installing WebDriver

**Arch/Manjaro:**
```bash
sudo pacman -S geckodriver    # for Firefox
sudo pacman -S chromedriver   # for Chrome
```

**Ubuntu/Debian:**
```bash
# geckodriver - download from https://github.com/mozilla/geckodriver/releases
# chromedriver - download from https://chromedriver.chromium.org/downloads
```

**macOS:**
```bash
brew install geckodriver
brew install chromedriver
```

## Installation

Add to your `Cargo.toml`:

```toml
[dependencies]
surfer-rs = "0.1"
```

### Feature Flags

| Feature | Description | Default |
|---------|-------------|---------|
| `smol-runtime` | Use the built-in smol runtime support | Yes |
| `cli` | Build the CLI binary | Yes |

Runtime support is smol-based by default:
```toml
[dependencies]
surfer-rs = "0.1"
```

## CLI Usage

```bash
# Start browser (launches geckodriver + Firefox)
surfer start
surfer start --browser chrome --headless

# Navigate
surfer goto example.com
surfer back
surfer forward
surfer refresh

# Discover elements
surfer inputs          # list input/textarea/select elements
surfer buttons         # list buttons
surfer links           # list links
surfer find "selector" # find by CSS selector
surfer context "selector"  # show DOM context

# Interact by index (from inputs/buttons output)
surfer input 0 "hello"     # set input value
surfer click 0             # click button by index
surfer select 2 "option"   # select dropdown option
surfer enter 0             # press Enter

# Interact by selector
surfer click "button.submit"
surfer type "#email" "user@example.com"
surfer fill email "user@example.com"  # by name or id
surfer search "query"      # find search box and submit
surfer submit              # submit first form

# Utilities
surfer screenshot output.png
surfer js "document.title"
surfer html
surfer url
surfer title

# Stop browser
surfer stop
surfer status
```

## Library Usage

```rust
use surfer_rs::{WebDriverSurfer, Surfer, BrowserConfig};

fn main() -> Result<(), surfer_rs::SurferError> {
    smol::block_on(async move {
    // Connect to running WebDriver (start geckodriver first)
    let config = BrowserConfig::default();
    let browser = WebDriverSurfer::connect(&config).await?;

    // Navigate
    browser.goto("https://example.com").await?;

    // Discover
    let inputs = browser.inputs().await?;
    for input in &inputs {
        println!("{}", input);
    }

    // Interact
    browser.set_input(0, "hello").await?;
    browser.click_button(0).await?;

    // Or by selector
    browser.fill("email", "user@example.com").await?;
    browser.click("button[type=submit]").await?;

    Ok(())
    })
}
```

## Architecture

```
surfer (Rust)
   ↓
surfer-rs::webdriver (internal WebDriver client module)
   ↓
geckodriver/chromedriver (WebDriver server)
   ↓
Firefox/Chrome (browser)
```

## State Persistence

Browser state is stored at `~/.local/share/surfer/browser.json`:

```json
{
  "pid": 12345,
  "port": 4444,
  "browser_type": "firefox",
  "webdriver_url": "http://localhost:4444",
  "started_at": "2024-01-24T10:30:00Z"
}
```

## License

MIT
