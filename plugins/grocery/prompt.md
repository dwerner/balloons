# Canadian Grocery Domain

Shop for groceries at Canadian stores without dealing with their broken websites.

## Supported Chains

**PC Express (Loblaw brands):**
- Real Canadian Superstore
- No Frills
- Loblaws
- Zehrs
- Fortinos
- Provigo
- Maxi
- Valu-mart
- Your Independent Grocer

**Other chains:**
- SaveOn Foods

## Two Approaches

### 1. Browser Automation (Recommended)

Use an automated browser to interact with the grocery site directly. This handles authentication,
searches, and cart management through the actual website.

**Quick Shopping Workflow:**
1. `grocery_browser_start` - Launch browser (auto-dismisses cookie popup)
2. Navigate to search: `grocery_browser_goto(url="https://www.realcanadiansuperstore.ca/search?search-bar=bread")`
3. `grocery_browser_list_products` - See available products with indices
4. `grocery_browser_add_product(index=N)` - Add item to cart
5. `grocery_browser_cart_count` - Verify cart updated
6. `grocery_browser_stop` - Close when done

**Exploration Workflow:**
1. `grocery_browser_start` - Launch browser
2. `grocery_browser_see` / `grocery_browser_inputs` / `grocery_browser_buttons` - Explore the page
3. `grocery_browser_fill` / `grocery_browser_click_button` - Interact with forms
4. `grocery_browser_screenshot` - See what the page looks like
5. `grocery_browser_stop` - Close when done

### 2. API + Local Cart (Limited)

Use reverse-engineered APIs for search (may require authentication) and maintain a local cart
that exports to a browser bookmarklet.

**Workflow:**
1. Set your store with `grocery_set_store`
2. Search for products with `grocery_search`
3. Add items to local cart with `grocery_cart_add`
4. Export with `grocery_cart_export`

## Browser Tools

**grocery_browser_hosts** - List available hosts where the browser can run (local + supervisor hosts)

**grocery_browser_set_host** - Select which host runs the browser
- `grocery_browser_set_host(host="local")` - Run headless on this machine
- `grocery_browser_set_host(host="living-room")` - Run on a remote display (requires chromedriver running there)

**grocery_browser_start** - Launch browser and navigate to grocery site
- `grocery_browser_start()` - Opens default site based on your banner
- `grocery_browser_start(url="...", headless=True)` - Custom URL, no visible window
- `grocery_browser_start(webdriver_url="http://192.168.1.100:4444")` - Connect to remote chromedriver over LAN

**grocery_browser_see** - Get structured view of page (content sections, forms, navigation)

**grocery_browser_inputs** - List all input fields with their indices

**grocery_browser_buttons** - List all buttons with their indices

**grocery_browser_fill** - Fill an input field
- `grocery_browser_fill(index=0, value="milk")`

**grocery_browser_click_button** - Click a button by index
- `grocery_browser_click_button(index=2)`

**grocery_browser_click** - Click element by CSS selector
- `grocery_browser_click(selector="#sign-in-btn")`

**grocery_browser_goto** - Navigate to a URL

**grocery_browser_search** - Search via direct URL navigation (more reliable than search box)
- `grocery_browser_search(query="2% milk")`

**grocery_browser_get_products** - Extract structured product data from search results
- Returns: code, name, size, price, unit price, image URL, button index
- Data is parsed from product cards on the page

**grocery_browser_get_product_detail** - Get detailed product info including nutrition facts
- Navigate to a product page first (click a product link or use goto)
- Extracts: name, brand, price, description, nutrition facts, ingredients

**grocery_browser_dismiss_popups** - Dismiss annoying popups (surveys, chat widgets, banners)

**grocery_browser_screenshot** - Take a screenshot (returns file path)

**grocery_browser_find_stores** - Find stores near a location
- `grocery_browser_find_stores(location="V5K 0A1")` - Search by postal code
- `grocery_browser_find_stores(location="Vancouver BC")` - Search by city
- Returns store IDs you can use with `grocery_set_store`

**grocery_browser_js** - Execute JavaScript on the page

**grocery_browser_list_products** - Find all "Add to cart" buttons and list products with indices

**grocery_browser_add_product** - Add a product to cart by button index
- `grocery_browser_add_product(index=30)`

**grocery_browser_cart_count** - Get the current cart item count

**grocery_browser_stop** - Close the browser

## API/Cart Tools

### Store Setup

**grocery_set_store** - Set your preferred store
- For PC Express: `grocery_set_store(store_id="1511", banner="superstore")`
- For SaveOn: `grocery_set_store(store_id="2001", banner="saveon")`

**grocery_list_banners** - List all available store banners/chains

### Product Search (API)

**grocery_search** - Search for products via API
- May require authentication for PC Express
- Returns: name, price, unit price, product code

### Cart Management

**grocery_cart_add** - Add a product to your local cart

**grocery_cart_remove** - Remove a product from cart

**grocery_cart_update** - Update quantity of a cart item

**grocery_cart_show** - Show current cart with totals

**grocery_cart_clear** - Empty the cart

**grocery_cart_export** - Export cart as browser bookmarklets

## Tips

- The browser tools let you interactively explore and figure out how to accomplish tasks
- Use `grocery_browser_see` to understand page structure
- Use `grocery_browser_screenshot` to visually verify state
- Login flows: use `grocery_browser_inputs` and `grocery_browser_fill` for credentials
- 2FA: watch for SMS/email codes, use `grocery_browser_fill` to enter them
