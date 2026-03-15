# Canadian Grocery Domain

Shop for groceries at Canadian stores with automatic price tracking and product data harvesting.

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

## Quick Start

**IMPORTANT: Set a store first!** Prices vary by store.

```
1. grocery_store_info               # Check current store
2. grocery_browser_start            # Launch browser
3. grocery_browser_find_stores("V5K 0A1")  # Find stores by postal code
4. grocery_store_select("1527")     # Set your store
5. grocery_search_query("milk")     # Search - prices are now harvested!
6. grocery_product_goto(code="...")  # View details - nutrition is harvested!
7. grocery_data_products            # See what's been collected
8. grocery_data_prices("20962518")  # Price history for a product
```

## Tool Organization by View

| Prefix | View | Purpose |
|--------|------|---------|
| `grocery_store_*` | Store Selection | Find and select stores (required first!) |
| `grocery_browser_*` | Browser/Global | Browser lifecycle, navigation, screenshots |
| `grocery_search_*` | Search Results | Product search and listing |
| `grocery_product_*` | Product Detail | Detailed info, nutrition, add to cart |
| `grocery_cart_*` | Cart | Cart management and quantities |
| `grocery_data_*` | Data Layer | Price tracking, product database |

---

## Store Tools (`grocery_store_*`)

**Setting a store is required before shopping.** Prices are store-specific.

**grocery_store_info** - Show current store and price data stats

**grocery_store_select** - Set the active store
- `grocery_store_select(store_id="1527", banner="superstore")`

**grocery_set_store** - Same as grocery_store_select

**grocery_list_banners** - List available chains/banners

**grocery_browser_find_stores** - Search for stores by location (requires browser)
- `grocery_browser_find_stores(location="V5K 0A1")`

---

## Browser Tools (`grocery_browser_*`)

### Lifecycle

**grocery_browser_start** - Launch browser
- Automatically sets the saved store on startup

**grocery_browser_stop** - Close browser

**grocery_browser_hosts** - List available hosts (local + remote)

**grocery_browser_set_host** - Select browser host
- `grocery_browser_set_host(host="living-room")` for remote display

### Navigation

**grocery_browser_goto** - Navigate to URL

**grocery_browser_screenshot** - Take screenshot

**grocery_browser_dismiss_popups** - Dismiss overlays

### Low-Level

**grocery_browser_see** - Structured page view

**grocery_browser_inputs/buttons** - List interactive elements

**grocery_browser_fill/click_button** - Interact with elements

**grocery_browser_js** - Execute JavaScript

---

## Search View Tools (`grocery_search_*`)

**grocery_search_query** - Search for products
- `grocery_search_query(query="2% milk")`
- **Automatically harvests prices** for products shown

**grocery_search_products** - Get structured product list
- Shows: name, price, cart quantity, URL, button indices
- Cart items show with: `🛒 2 in cart`

**grocery_search_add_to_cart** - Add by button index
- `grocery_search_add_to_cart(index=34)`

---

## Product Detail Tools (`grocery_product_*`)

**grocery_product_goto** - Navigate to product page
- `grocery_product_goto(url="/en/p/product/20962518_EA")`
- `grocery_product_goto(code="20962518")`

**grocery_product_info** - Get full details
- **Automatically harvests nutrition facts and ingredients**
- Includes: name, brand, price, description, nutrition, ingredients

**grocery_product_add_to_cart** - Add to cart
- `grocery_product_add_to_cart(quantity=2)`

---

## Cart Tools (`grocery_cart_*`)

**grocery_cart_count** - Current cart item count

**grocery_cart_items** - Show locally tracked cart

**grocery_cart_view** - Navigate to cart review page

**grocery_cart_increase/decrease** - Modify quantities
- `grocery_cart_increase(product_name="Milk")`

**grocery_cart_sync** - Sync local tracking with page

**grocery_cart_clear_local** - Clear local tracking

---

## Data Tools (`grocery_data_*`)

The plugin automatically harvests product and price data as you browse.

**grocery_data_products** - List harvested products
- `grocery_data_products()` - Show all
- `grocery_data_products(query="milk")` - Search

**grocery_data_prices** - Price history for a product
- `grocery_data_prices(code="20962518")`
- Shows price over time, per store

**grocery_data_product_detail** - Full product info from database
- `grocery_data_product_detail(code="20962518")`
- Includes nutrition facts if harvested

**grocery_data_export** - Export stats and file paths

### Data Storage

Data is stored in `~/.balloons/plugins/grocery/data/`:
- `products.jsonl` - Product info (name, brand, size, nutrition, ingredients)
- `prices.jsonl` - Price records (store, date, price, sale status)

---

## Tips

- **Set store first!** Use `grocery_store_info` to check, `grocery_store_select` to set
- **Data is harvested automatically** - just browse products normally
- **Price history builds over time** - check back after shopping trips
- **Nutrition requires detail page** - use `grocery_product_goto` then `grocery_product_info`
- **Screenshot for debugging** - `grocery_browser_screenshot`
