# Grocery Plugin Architecture

## Core Concepts

### 1. Store Context (Required First)
Before any shopping, the user must set a store. Prices are store-specific.

### 2. View-Based Tools
Tools are namespaced by the view they operate on:

| Namespace | View | Purpose |
|-----------|------|---------|
| `grocery_store_*` | Store Locator | Find and select stores |
| `grocery_search_*` | Search Results | Product search and listing |
| `grocery_product_*` | Product Detail | Detailed info, nutrition, add to cart |
| `grocery_cart_*` | Cart | View/modify cart |
| `grocery_data_*` | Data Layer | Price tracking, product database |

### 3. Data Harvesting
Every product interaction harvests data:
- **Search results**: Basic product info + current price
- **Product detail**: Full info + nutrition facts + ingredients

### 4. Price Tracking
Prices are stored with:
- `product_code`
- `store_id`
- `banner`
- `date` (YYYY-MM-DD)
- `price`
- `unit_price`
- `on_sale`
- `was_price`

## Tool Inventory

### Store Tools (`grocery_store_*`)

```
grocery_store_find(location)     # Search for stores by postal code/city
grocery_store_select(store_id)   # Set the active store (required before shopping)
grocery_store_info()             # Show current store
grocery_store_list_banners()     # List available chains
```

### Search View Tools (`grocery_search_*`)

```
grocery_search_query(query)      # Navigate to search and execute
grocery_search_products(limit)   # Get products from current search results
grocery_search_add(index)        # Add product to cart by index
grocery_search_next_page()       # Go to next page of results
```

### Product View Tools (`grocery_product_*`)

```
grocery_product_goto(code)       # Navigate to product detail page
grocery_product_info()           # Get full product details + nutrition
grocery_product_add(quantity)    # Add to cart from detail page
grocery_product_reviews()        # Get product reviews
```

### Cart Tools (`grocery_cart_*`)

```
grocery_cart_view()              # Show cart contents
grocery_cart_count()             # Get item count
grocery_cart_increase(product)   # Increase quantity
grocery_cart_decrease(product)   # Decrease quantity
grocery_cart_remove(product)     # Remove from cart
grocery_cart_clear()             # Empty cart
```

### Data Tools (`grocery_data_*`)

```
grocery_data_products()          # List harvested products
grocery_data_prices(code)        # Price history for a product
grocery_data_export()            # Export all data
grocery_data_search(query)       # Search harvested products
```

### Browser Tools (`grocery_browser_*`)

Low-level browser control (usually not needed directly):

```
grocery_browser_start()          # Start browser
grocery_browser_stop()           # Stop browser
grocery_browser_screenshot()     # Take screenshot
grocery_browser_goto(url)        # Navigate to URL
grocery_browser_js(script)       # Execute JavaScript
```

## Data Storage

### File: `~/.balloons/plugins/grocery/products.jsonl`

One JSON object per line:
```json
{"code": "20962518", "name": "Dairyland 2% Milk", "brand": "Dairyland", "size": "4L", "nutrition": {...}, "ingredients": "...", "updated": "2025-01-15"}
```

### File: `~/.balloons/plugins/grocery/prices.jsonl`

One JSON object per line:
```json
{"code": "20962518", "store_id": "1527", "banner": "superstore", "date": "2025-01-15", "price": 5.99, "unit_price": 0.15, "on_sale": false}
```

## Workflow Examples

### First-Time Setup
```
1. grocery_store_find("V5K 0A1")      # Find nearby stores
2. grocery_store_select("1527")       # Select Langford Superstore
```

### Shopping Session
```
1. grocery_search_query("milk")       # Search for milk
2. grocery_search_products()          # View results (prices harvested)
3. grocery_product_goto("20962518")   # View details (nutrition harvested)
4. grocery_product_add(2)             # Add 2 to cart
5. grocery_cart_view()                # Review cart
```

### Price Tracking
```
1. grocery_data_prices("20962518")    # See price history
2. grocery_data_products()            # Browse harvested products
```

## View Detection

The plugin can detect which view we're on by URL:

| URL Pattern | View |
|-------------|------|
| `/store-locator*` | Store Locator |
| `/search*` | Search Results |
| `/p/*` or `/en/*/p/*` | Product Detail |
| `/cart*` | Cart |
| `/*` (root) | Home |

This enables automatic context injection and validation.
