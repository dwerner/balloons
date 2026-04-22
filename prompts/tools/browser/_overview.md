## Browser Automation Tools

Tools for web browser automation via WebDriver. Use these when you need to:
- Navigate to websites and interact with web pages
- Fill out forms, click buttons, and submit data
- Extract information from web pages
- Take screenshots of web content
- Execute JavaScript in the browser context

### Why Use Browser Tools?

These tools provide programmatic access to a real web browser (Firefox or Chrome), enabling:
- **Web scraping**: Extract data from dynamic JavaScript-rendered pages
- **Form automation**: Fill out and submit web forms
- **Testing**: Verify web application behavior
- **Research**: Browse and gather information from websites

### Browser Lifecycle

1. **Start**: Call `browser_start` to launch a browser session
2. **Navigate**: Use `browser_goto` to visit URLs
3. **Interact**: Use `browser_see`, `browser_click`, `browser_fill`, etc.
4. **Stop**: Call `browser_stop` when done (important to free resources)

### Recommended Workflow

1. Start with `browser_see` after navigation to understand page structure
2. Use `browser_inputs` and `browser_buttons` to discover interactive elements
3. Interact by index (from discovery) or CSS selector
4. Always call `browser_stop` when finished

### Element Selection

Most interaction tools accept either:
- **CSS selector**: `"#login-button"`, `".submit-btn"`, `"input[name='email']"`
- **Index**: From `browser_inputs`, `browser_buttons`, or `browser_links` discovery

Using indices is often more reliable as they're based on actual visible elements.
