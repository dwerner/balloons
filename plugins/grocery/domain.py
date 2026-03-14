"""Canadian Grocery domain plugin.

Provides grocery shopping capabilities using reverse-engineered APIs:
- PC Express (Loblaw): Superstore, No Frills, Loblaws, Zehrs, etc.
- SaveOn Foods

Maintains a local cart that can be exported for injection into the real site.
"""

import json
import aiohttp
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING
from datetime import datetime
from enum import Enum

from codegen.ws_expose import ws_expose
from ..base import DomainEvent, DecoratedStatefulDomain, ToolResult
from ..decorators import llm_callable, Param
from ..storage import JsonFileStorage

if TYPE_CHECKING:
    from session import Session


class GroceryChain(Enum):
    """Supported grocery chains."""
    PCEXPRESS = "pcexpress"  # Loblaw brands
    SAVEON = "saveon"  # SaveOn Foods


# PC Express API configuration
PC_EXPRESS_API = "https://api.pcexpress.ca"
PC_EXPRESS_API_KEY = "C1xujSegT5j3ap3yexJjqhOfELwGKYvz"

# SaveOn Foods API configuration
SAVEON_API = "https://storefrontgateway.saveonfoods.com"

# Available store banners (PC Express / Loblaw)
PCEXPRESS_BANNERS = {
    "superstore": "Real Canadian Superstore",
    "nofrills": "No Frills",
    "loblaws": "Loblaws",
    "zehrs": "Zehrs",
    "fortinos": "Fortinos",
    "provigo": "Provigo",
    "maxi": "Maxi",
    "valumart": "Valu-mart",
    "independentcitymarket": "Independent City Market",
    "yourindependentgrocer": "Your Independent Grocer",
}

# Combined banners including SaveOn
ALL_BANNERS = {
    **PCEXPRESS_BANNERS,
    "saveon": "SaveOn Foods",
}

# Map banners to their chain
BANNER_TO_CHAIN = {
    **{k: GroceryChain.PCEXPRESS for k in PCEXPRESS_BANNERS},
    "saveon": GroceryChain.SAVEON,
}


@dataclass
class CartItem:
    """A product in the local cart."""
    product_code: str
    name: str
    price: float
    unit: str  # "each", "per kg", etc.
    quantity: int
    image_url: str | None = None
    brand: str | None = None
    size: str | None = None
    chain: str = "pcexpress"  # Which chain this product is from

    def to_dict(self) -> dict:
        return {
            "product_code": self.product_code,
            "name": self.name,
            "price": self.price,
            "unit": self.unit,
            "quantity": self.quantity,
            "image_url": self.image_url,
            "brand": self.brand,
            "size": self.size,
            "chain": self.chain,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CartItem":
        return cls(
            product_code=data["product_code"],
            name=data["name"],
            price=data["price"],
            unit=data["unit"],
            quantity=data["quantity"],
            image_url=data.get("image_url"),
            brand=data.get("brand"),
            size=data.get("size"),
            chain=data.get("chain", "pcexpress"),
        )


@dataclass
class GroceryState:
    """Per-session grocery state."""
    store_id: str | None = None
    banner: str = "superstore"
    chain: GroceryChain = GroceryChain.PCEXPRESS
    auth_token: str | None = None  # Bearer token for PC Express
    cart: dict[str, CartItem] = field(default_factory=dict)
    # Cache of recent search results for quick add
    last_search_results: list[dict] = field(default_factory=list)
    # Browser host: "local" or a supervisor host name
    browser_host: str = "local"
    # Browser instance for web automation (not serialized)
    _browser: Any = field(default=None, repr=False)

    def to_dict(self) -> dict:
        # Note: _browser is not serialized
        return {
            "store_id": self.store_id,
            "banner": self.banner,
            "chain": self.chain.value,
            "auth_token": self.auth_token,
            "browser_host": self.browser_host,
            "cart": {k: v.to_dict() for k, v in self.cart.items()},
            "last_search_results": self.last_search_results,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GroceryState":
        cart = {}
        for k, v in data.get("cart", {}).items():
            cart[k] = CartItem.from_dict(v)
        chain_str = data.get("chain", "pcexpress")
        chain = GroceryChain(chain_str) if chain_str else GroceryChain.PCEXPRESS
        return cls(
            store_id=data.get("store_id"),
            banner=data.get("banner", "superstore"),
            chain=chain,
            auth_token=data.get("auth_token"),
            browser_host=data.get("browser_host", "local"),
            cart=cart,
            last_search_results=data.get("last_search_results", []),
        )


# In-memory session states
_session_states: dict[str, GroceryState] = {}

# Persistent storage
_storage: JsonFileStorage | None = None


def _get_storage() -> JsonFileStorage:
    global _storage
    if _storage is None:
        _storage = JsonFileStorage("grocery")
    return _storage


def _get_state(session_id: str) -> GroceryState:
    """Get or create state for a session."""
    if session_id not in _session_states:
        _session_states[session_id] = GroceryState()
    return _session_states[session_id]


class GroceryDomain(DecoratedStatefulDomain):
    """Canadian grocery shopping domain.

    Supports multiple chains:
    - PC Express (Loblaw): Superstore, No Frills, Loblaws, Zehrs, etc.
    - SaveOn Foods

    Tools:
        - grocery_set_store: Set the store to shop at
        - grocery_list_banners: List available store banners
        - grocery_search: Search for products
        - grocery_cart_add: Add product to cart
        - grocery_cart_remove: Remove product from cart
        - grocery_cart_update: Update cart item quantity
        - grocery_cart_show: Show cart contents
        - grocery_cart_clear: Empty the cart
        - grocery_cart_export: Export cart for browser injection
    """

    @property
    def id(self) -> str:
        return "grocery"

    @property
    def name(self) -> str:
        return "Canadian Grocery"

    @property
    def version(self) -> str:
        return "0.1.0"

    def get_prompt(self) -> str:
        """Load prompt from prompt.md file."""
        import os
        prompt_path = os.path.join(os.path.dirname(__file__), "prompt.md")
        try:
            with open(prompt_path, "r") as f:
                return f.read()
        except FileNotFoundError:
            return "## Grocery Domain\n\nUse grocery_* tools to search and build a shopping cart."

    # --- Store Setup ---

    @llm_callable(
        description="""Set the store to shop at. Required before searching for products.

For PC Express (Loblaw) stores: Use banner like 'superstore', 'nofrills', 'loblaws'
For SaveOn Foods: Use banner='saveon'""",
        params={
            "store_id": Param(str, "Store ID/number. Find at pcexpress.ca/store-locator or saveonfoods.com/store-locator"),
            "banner": Param(str, "Store banner (default: superstore)",
                          enum=list(ALL_BANNERS.keys()), required=False),
        }
    )
    async def grocery_set_store(
        self,
        store_id: str,
        banner: str = "superstore",
        session: "Session" = None
    ) -> ToolResult:
        """Set the store for shopping."""
        state = _get_state(session.id)
        state.store_id = store_id
        state.banner = banner
        state.chain = BANNER_TO_CHAIN.get(banner, GroceryChain.PCEXPRESS)

        banner_name = ALL_BANNERS.get(banner, banner)
        chain_name = "SaveOn Foods" if state.chain == GroceryChain.SAVEON else "PC Express"
        return ToolResult(
            f"Store set to {banner_name} (ID: {store_id}, Chain: {chain_name}).\n"
            f"You can now search for products with grocery_search."
        )

    @llm_callable(description="List available store banners (chains) for Canadian grocery stores.")
    async def grocery_list_banners(self, session: "Session" = None) -> ToolResult:
        """List available store banners."""
        lines = ["Available store banners:\n"]
        lines.append("**PC Express (Loblaw) Stores:**")
        for key, name in PCEXPRESS_BANNERS.items():
            lines.append(f"  - {key}: {name}")
        lines.append("\n**Other Chains:**")
        lines.append("  - saveon: SaveOn Foods")
        return ToolResult("\n".join(lines))

    # --- Product Search ---

    @llm_callable(
        description="Search for grocery products. Returns product codes, names, prices, and unit prices.",
        params={
            "query": Param(str, "Search query (e.g., 'milk 2%', 'bananas', 'bread')"),
            "limit": Param(int, "Max results to return (default: 10)", required=False),
        }
    )
    async def grocery_search(
        self,
        query: str,
        limit: int = 10,
        session: "Session" = None
    ) -> ToolResult:
        """Search for products."""
        state = _get_state(session.id)

        if not state.store_id:
            return ToolResult(
                "No store set. Use grocery_set_store first.\n"
                "Examples:\n"
                "  grocery_set_store(store_id='1511', banner='superstore')\n"
                "  grocery_set_store(store_id='2001', banner='saveon')",
                is_error=True
            )

        try:
            if state.chain == GroceryChain.SAVEON:
                results = await self._search_saveon(
                    query=query,
                    store_id=state.store_id,
                    limit=limit,
                )
            else:
                results = await self._search_pcexpress(
                    query=query,
                    store_id=state.store_id,
                    banner=state.banner,
                    limit=limit,
                )
        except Exception as e:
            return ToolResult(f"Search failed: {e}", is_error=True)

        if not results:
            return ToolResult(f"No products found for '{query}'")

        # Cache results for quick add
        state.last_search_results = results

        # Format results
        chain_name = "SaveOn" if state.chain == GroceryChain.SAVEON else "PC Express"
        lines = [f"Found {len(results)} products for '{query}' ({chain_name}):\n"]
        for i, product in enumerate(results, 1):
            price_str = f"${product['price']:.2f}"
            if product.get('unit_price'):
                price_str += f" ({product['unit_price']})"

            name = product['name']
            if product.get('brand'):
                name = f"{product['brand']} {name}"
            if product.get('size'):
                name += f" ({product['size']})"

            lines.append(
                f"{i}. {name}\n"
                f"   Price: {price_str}\n"
                f"   Code: {product['code']}"
            )

        lines.append("\nUse grocery_cart_add(product_code='...') to add items to your cart.")
        return ToolResult("\n".join(lines))

    async def _search_pcexpress(
        self,
        query: str,
        store_id: str,
        banner: str,
        limit: int = 10,
    ) -> list[dict]:
        """Search the PC Express API for products."""
        url = f"{PC_EXPRESS_API}/product-facade/v3/products/search"

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:148.0) Gecko/20100101 Firefox/148.0",
            "Origin": "https://www.realcanadiansuperstore.ca",
            "Referer": "https://www.realcanadiansuperstore.ca/",
            "Site-Banner": banner,
            "baseSiteId": banner,
            "Business-User-Agent": "PCXWEB",
            "x-apikey": PC_EXPRESS_API_KEY,
            "x-loblaw-tenant-id": "ONLINE_GROCERIES",
            "x-channel": "web",
            "x-application-type": "web",
        }

        body = {
            "query": query,
            "storeId": store_id,
            "banner": banner,
            "from": 0,
            "size": limit,
            "lang": "en",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "pickupType": "STORE",
        }

        async with aiohttp.ClientSession() as http_session:
            async with http_session.post(url, headers=headers, json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"API returned {resp.status}: {text[:200]}")
                data = await resp.json()

        products = []
        for item in data.get("results", []):
            product = {
                "code": item.get("code", ""),
                "name": item.get("name", "Unknown"),
                "brand": item.get("brand"),
                "size": item.get("packageSize"),
                "price": 0.0,
                "unit_price": None,
                "image_url": None,
                "chain": "pcexpress",
            }

            # Extract price
            prices = item.get("prices", {})
            if prices.get("price"):
                product["price"] = prices["price"].get("value", 0)
            elif prices.get("wasPrice"):
                product["price"] = prices["wasPrice"].get("value", 0)

            # Unit price (e.g., "per 100g")
            if prices.get("comparisonPrices"):
                for cp in prices["comparisonPrices"]:
                    if cp.get("value") and cp.get("unit"):
                        product["unit_price"] = f"${cp['value']:.2f}/{cp['unit']}"
                        break

            # Image URL
            if item.get("imageAssets"):
                for img in item["imageAssets"]:
                    if img.get("mediumUrl"):
                        product["image_url"] = img["mediumUrl"]
                        break

            products.append(product)

        return products

    async def _search_saveon(
        self,
        query: str,
        store_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Search the SaveOn Foods API for products."""
        # SaveOn uses a GET endpoint
        url = f"{SAVEON_API}/api/stores/{store_id}/preview"

        params = {
            "q": query,
            "popularTake": limit,
        }

        headers = {
            "Accept": "application/json",
            "X-Site-Host": "saveonfoods.com",
            "X-Shopping-Mode": "pickup",
        }

        async with aiohttp.ClientSession() as http_session:
            async with http_session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"SaveOn API returned {resp.status}: {text[:200]}")

                data = await resp.json()

        products = []

        # SaveOn returns products in a different structure
        # They have "popularProducts" and "searchResults" depending on endpoint
        items = data.get("products", [])
        if not items:
            items = data.get("popularProducts", [])
        if not items:
            # Try the search results structure
            search_results = data.get("searchResults", {})
            items = search_results.get("products", [])

        for item in items[:limit]:
            product = {
                "code": str(item.get("productId", item.get("id", ""))),
                "name": item.get("name", "Unknown"),
                "brand": item.get("brand"),
                "size": item.get("packageSize") or item.get("size"),
                "price": 0.0,
                "unit_price": None,
                "image_url": None,
                "chain": "saveon",
            }

            # Extract price - SaveOn uses different field names
            if item.get("price"):
                product["price"] = float(item["price"])
            elif item.get("currentPrice"):
                product["price"] = float(item["currentPrice"])
            elif item.get("pricing", {}).get("price"):
                product["price"] = float(item["pricing"]["price"])

            # Unit price
            if item.get("unitPrice"):
                product["unit_price"] = item["unitPrice"]
            elif item.get("pricing", {}).get("unitPrice"):
                product["unit_price"] = item["pricing"]["unitPrice"]

            # Image
            if item.get("imageUrl"):
                product["image_url"] = item["imageUrl"]
            elif item.get("images") and len(item["images"]) > 0:
                product["image_url"] = item["images"][0]

            products.append(product)

        return products

    # --- Cart Management ---

    @llm_callable(
        description="Add a product to your local cart. Use the product_code from search results.",
        params={
            "product_code": Param(str, "Product code from search results"),
            "quantity": Param(int, "Quantity to add (default: 1)", required=False),
        }
    )
    async def grocery_cart_add(
        self,
        product_code: str,
        quantity: int = 1,
        session: "Session" = None
    ) -> ToolResult:
        """Add a product to the cart."""
        state = _get_state(session.id)

        # Look up product in last search results
        product = None
        for p in state.last_search_results:
            if p["code"] == product_code:
                product = p
                break

        if not product:
            return ToolResult(
                f"Product code '{product_code}' not found in recent search results.\n"
                "Please search for the product first with grocery_search.",
                is_error=True
            )

        # Add or update cart
        if product_code in state.cart:
            state.cart[product_code].quantity += quantity
            action = "Updated"
        else:
            state.cart[product_code] = CartItem(
                product_code=product_code,
                name=product["name"],
                price=product["price"],
                unit="each",
                quantity=quantity,
                image_url=product.get("image_url"),
                brand=product.get("brand"),
                size=product.get("size"),
                chain=product.get("chain", state.chain.value),
            )
            action = "Added"

        item = state.cart[product_code]
        total = sum(i.price * i.quantity for i in state.cart.values())

        return ToolResult(
            f"{action}: {item.quantity}x {item.name} @ ${item.price:.2f}\n"
            f"Cart total: ${total:.2f} ({len(state.cart)} items)"
        )

    @llm_callable(
        description="Remove a product from your cart.",
        params={
            "product_code": Param(str, "Product code to remove"),
        }
    )
    async def grocery_cart_remove(
        self,
        product_code: str,
        session: "Session" = None
    ) -> ToolResult:
        """Remove a product from the cart."""
        state = _get_state(session.id)

        if product_code not in state.cart:
            return ToolResult(f"Product '{product_code}' not in cart", is_error=True)

        item = state.cart.pop(product_code)
        total = sum(i.price * i.quantity for i in state.cart.values())

        return ToolResult(
            f"Removed: {item.name}\n"
            f"Cart total: ${total:.2f} ({len(state.cart)} items)"
        )

    @llm_callable(
        description="Update the quantity of an item in your cart.",
        params={
            "product_code": Param(str, "Product code to update"),
            "quantity": Param(int, "New quantity (0 to remove)"),
        }
    )
    async def grocery_cart_update(
        self,
        product_code: str,
        quantity: int,
        session: "Session" = None
    ) -> ToolResult:
        """Update cart item quantity."""
        state = _get_state(session.id)

        if product_code not in state.cart:
            return ToolResult(f"Product '{product_code}' not in cart", is_error=True)

        if quantity <= 0:
            return await self.grocery_cart_remove(product_code, session=session)

        item = state.cart[product_code]
        item.quantity = quantity
        total = sum(i.price * i.quantity for i in state.cart.values())

        return ToolResult(
            f"Updated: {item.quantity}x {item.name}\n"
            f"Cart total: ${total:.2f} ({len(state.cart)} items)"
        )

    @llm_callable(description="Show the current contents of your cart.")
    async def grocery_cart_show(self, session: "Session" = None) -> ToolResult:
        """Show cart contents."""
        state = _get_state(session.id)

        if not state.cart:
            return ToolResult("Cart is empty. Use grocery_search and grocery_cart_add to add items.")

        lines = ["Your cart:\n"]
        subtotal = 0.0

        for item in state.cart.values():
            item_total = item.price * item.quantity
            subtotal += item_total

            name = item.name
            if item.brand:
                name = f"{item.brand} {name}"
            if item.size:
                name += f" ({item.size})"

            lines.append(
                f"  {item.quantity}x {name}\n"
                f"      ${item.price:.2f} each = ${item_total:.2f}"
            )

        lines.append(f"\nSubtotal: ${subtotal:.2f}")
        lines.append(f"Items: {sum(i.quantity for i in state.cart.values())}")
        lines.append("\nUse grocery_cart_export to get a bookmarklet for the real site.")

        return ToolResult("\n".join(lines))

    @llm_callable(description="Clear all items from your cart.")
    async def grocery_cart_clear(self, session: "Session" = None) -> ToolResult:
        """Clear the cart."""
        state = _get_state(session.id)
        count = len(state.cart)
        state.cart.clear()
        return ToolResult(f"Cart cleared ({count} items removed)")

    @llm_callable(
        description="""Export your cart for transfer to the grocery website.
Returns JavaScript bookmarklets you can paste into the browser console,
plus the raw JSON data for other integrations."""
    )
    async def grocery_cart_export(self, session: "Session" = None) -> ToolResult:
        """Export cart for browser injection."""
        state = _get_state(session.id)

        if not state.cart:
            return ToolResult("Cart is empty. Nothing to export.", is_error=True)

        # Group items by chain
        pcexpress_items = []
        saveon_items = []

        for item in state.cart.values():
            item_data = {
                "productCode": item.product_code,
                "quantity": item.quantity,
                "name": item.name,
            }
            if item.chain == "saveon":
                saveon_items.append(item_data)
            else:
                pcexpress_items.append(item_data)

        lines = [
            "# Cart Export\n",
            f"**{len(state.cart)} items, ${sum(i.price * i.quantity for i in state.cart.values()):.2f} total**\n",
        ]

        # PC Express bookmarklet
        if pcexpress_items:
            pcexpress_bookmarklet = f"""
(async function() {{
    const items = {json.dumps(pcexpress_items)};
    let added = 0;
    let failed = 0;

    for (const item of items) {{
        try {{
            const resp = await fetch('/api/cart/items', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{productCode: item.productCode, quantity: item.quantity}}),
                credentials: 'include',
            }});
            if (resp.ok) {{ added++; console.log('Added:', item.name); }}
            else {{ failed++; console.error('Failed:', item.name, resp.status); }}
        }} catch (e) {{ failed++; console.error('Error:', item.name, e); }}
        await new Promise(r => setTimeout(r, 200));
    }}
    alert(`Added ${{added}} items to cart.${{failed ? ' (' + failed + ' failed)' : ''}}`);
}})();
""".strip()

            lines.extend([
                f"## PC Express ({len(pcexpress_items)} items)\n",
                "Paste in browser console while on **realcanadiansuperstore.ca** or **nofrills.ca**:\n",
                "```javascript",
                pcexpress_bookmarklet,
                "```\n",
            ])

        # SaveOn bookmarklet
        if saveon_items:
            saveon_bookmarklet = f"""
(async function() {{
    const items = {json.dumps(saveon_items)};
    let added = 0;
    let failed = 0;

    for (const item of items) {{
        try {{
            const resp = await fetch('/api/cart/add', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{productId: item.productCode, quantity: item.quantity}}),
                credentials: 'include',
            }});
            if (resp.ok) {{ added++; console.log('Added:', item.name); }}
            else {{ failed++; console.error('Failed:', item.name, resp.status); }}
        }} catch (e) {{ failed++; console.error('Error:', item.name, e); }}
        await new Promise(r => setTimeout(r, 200));
    }}
    alert(`Added ${{added}} items to cart.${{failed ? ' (' + failed + ' failed)' : ''}}`);
}})();
""".strip()

            lines.extend([
                f"## SaveOn Foods ({len(saveon_items)} items)\n",
                "Paste in browser console while on **saveonfoods.com**:\n",
                "```javascript",
                saveon_bookmarklet,
                "```\n",
            ])

        # LocalStorage approach
        all_items = {
            "pcexpress": pcexpress_items,
            "saveon": saveon_items,
        }
        localstorage_approach = f"""
// Store cart data in localStorage for a userscript
localStorage.setItem('balloons_grocery_cart', JSON.stringify({json.dumps(all_items)}));
console.log('Cart data stored. A userscript can read this and add items.');
""".strip()

        lines.extend([
            "## localStorage (for userscripts)\n",
            "```javascript",
            localstorage_approach,
            "```\n",
            "## Raw JSON\n",
            "```json",
            json.dumps(all_items, indent=2),
            "```",
        ])

        return ToolResult("\n".join(lines))

    # --- StatefulDomain Methods ---

    async def get_state(self, session: "Session") -> dict[str, Any] | None:
        """Return current grocery state."""
        if session.id not in _session_states:
            return None
        state = _session_states[session.id]
        return {
            "store_id": state.store_id,
            "banner": state.banner,
            "browser_host": state.browser_host,
            "cart_count": len(state.cart),
            "cart_total": sum(i.price * i.quantity for i in state.cart.values()),
            "cart_items": [i.to_dict() for i in state.cart.values()],
        }

    async def save_state(self, session: "Session") -> dict[str, Any]:
        """Save grocery state."""
        if session.id not in _session_states:
            return {}

        state = _session_states[session.id]
        state_dict = state.to_dict()

        # Persist to storage
        await _get_storage().save(session.id, state_dict)

        return state_dict

    async def load_state(self, session: "Session", state: dict[str, Any]) -> None:
        """Load grocery state."""
        if not state:
            state = await _get_storage().load(session.id)

        if not state:
            return

        _session_states[session.id] = GroceryState.from_dict(state)

    async def clear_state(self, session: "Session") -> None:
        """Clear grocery state."""
        if session.id in _session_states:
            # Close browser if running
            state = _session_states[session.id]
            if state._browser is not None:
                try:
                    await state._browser.disconnect()
                except Exception:
                    pass
            del _session_states[session.id]
        await _get_storage().delete(session.id)

    # --- Browser Automation Tools ---

    @ws_expose
    async def get_browser_hosts(self, session: "Session" = None) -> list[dict[str, Any]]:
        """Get list of available browser hosts for the UI.

        Returns list of {name, type, host, user, description, is_current} dicts.
        """
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        state = _get_state(session.id) if session else None
        current_host = state.browser_host if state else "local"

        hosts = []
        for name, host in config.hosts.items():
            hosts.append({
                "name": name,
                "type": host.type,
                "host": host.host,
                "user": host.user,
                "description": host.description or host.host or ("This machine" if host.type == "local" else name),
                "is_current": name == current_host,
            })
        return hosts

    @ws_expose
    async def set_browser_host(self, host: str, session: "Session" = None) -> dict[str, Any]:
        """Set the browser host. Returns {success, host, error?}."""
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        state = _get_state(session.id) if session else None

        if not state:
            return {"success": False, "error": "No session state"}

        if host not in config.hosts:
            available = list(config.hosts.keys())
            return {"success": False, "error": f"Unknown host '{host}'. Available: {available}"}

        state.browser_host = host
        return {"success": True, "host": host}

    @llm_callable(
        description="""List available hosts where the browser can run.
Returns local and any supervisor SSH hosts that could run chromedriver.""",
    )
    async def grocery_browser_hosts(self, session: "Session" = None) -> ToolResult:
        """List available browser hosts."""
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        state = _get_state(session.id)

        lines = ["Available browser hosts:"]
        lines.append("")

        for name, host in config.hosts.items():
            current = " (current)" if name == state.browser_host else ""
            if host.type == "local":
                lines.append(f"  • **local**{current} - This machine (headless only)")
            else:
                desc = host.description or host.host
                lines.append(f"  • **{name}**{current} - {desc} ({host.user}@{host.host})")

        lines.append("")
        lines.append("Use grocery_browser_set_host(host) to select where the browser runs.")
        lines.append("Remote hosts need chromedriver running: `DISPLAY=:0 chromedriver --port=4444 --allowed-ips=''`")

        return ToolResult("\n".join(lines))

    @llm_callable(
        description="""Set which host to use for browser automation.
Use 'local' for headless on this machine, or a supervisor host name for a remote display.""",
        params={
            "host": Param(str, "Host name from grocery_browser_hosts (e.g. 'local', 'living-room')"),
        }
    )
    async def grocery_browser_set_host(
        self,
        host: str,
        session: "Session" = None
    ) -> ToolResult:
        """Set the browser host."""
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        state = _get_state(session.id)

        if host not in config.hosts:
            available = ", ".join(config.hosts.keys())
            return ToolResult(f"Unknown host '{host}'. Available: {available}", is_error=True)

        state.browser_host = host

        host_config = config.hosts[host]
        if host_config.type == "local":
            return ToolResult(f"Browser host set to **local**. Will run headless on this machine.")
        else:
            return ToolResult(
                f"Browser host set to **{host}** ({host_config.user}@{host_config.host}).\n"
                f"Make sure chromedriver is running there:\n"
                f"  DISPLAY=:0 chromedriver --port=4444 --allowed-ips=''"
            )

    async def _dismiss_cookie_popup(self, browser) -> bool:
        """Dismiss cookie consent popups (OneTrust, etc.)."""
        import asyncio
        try:
            result = await browser.execute_js(
                '(function() { '
                'var btn = document.getElementById("onetrust-accept-btn-handler"); '
                'if (btn) { btn.click(); return true; } '
                'return false; '
                '})()'
            )
            if result == "true" or result is True:
                await asyncio.sleep(1)
                return True
        except Exception:
            pass
        return False

    @llm_callable(
        description="""Launch a browser and navigate to a grocery site.
Use this to start an interactive shopping session where you can see and interact with the page.
Uses the host selected via grocery_browser_set_host (defaults to local).""",
        params={
            "url": Param(str, "URL to navigate to (default: PC Express homepage)", required=False),
            "headless": Param(bool, "Run without visible window - only for local (default: False)", required=False),
            "webdriver_url": Param(str, "Override: direct WebDriver URL (ignores host setting)", required=False),
        }
    )
    async def grocery_browser_start(
        self,
        url: str | None = None,
        headless: bool = False,
        webdriver_url: str | None = None,
        session: "Session" = None
    ) -> ToolResult:
        """Launch browser for grocery shopping."""
        from supervisor_config import get_supervisor_config

        state = _get_state(session.id)

        if state._browser is not None:
            return ToolResult("Browser already running. Use grocery_browser_stop first.", is_error=True)

        try:
            import balloons_storage as bs
        except ImportError:
            return ToolResult(
                "balloons_storage not available. Browser automation requires the Rust extension.",
                is_error=True
            )

        # Determine URL based on chain/banner
        if url is None:
            if state.chain == GroceryChain.SAVEON:
                url = "https://www.saveonfoods.com/"
            else:
                banner_urls = {
                    "superstore": "https://www.realcanadiansuperstore.ca/",
                    "nofrills": "https://www.nofrills.ca/",
                    "loblaws": "https://www.loblaws.ca/",
                    "zehrs": "https://www.zehrs.ca/",
                }
                url = banner_urls.get(state.banner, "https://www.realcanadiansuperstore.ca/")

        # Determine webdriver URL from host setting if not overridden
        host_info = ""
        if webdriver_url is None and state.browser_host != "local":
            config = get_supervisor_config()
            host = config.hosts.get(state.browser_host)
            if host and host.type == "ssh" and host.host:
                webdriver_url = f"http://{host.host}:4444"
                host_info = f" on {state.browser_host}"
                headless = False  # Remote hosts have a display

        # For local, default to headless unless explicitly set
        if webdriver_url is None and not headless:
            headless = True  # Local defaults to headless

        try:
            # Create config - default to Chrome since geckodriver often missing
            config = bs.BrowserConfig(
                browser_type="chrome",
                headless=headless,
                webdriver_url=webdriver_url,
            )
            browser = bs.Browser(config)
            await browser.connect()
            await browser.goto(url)

            state._browser = browser

            # Dismiss cookie popup if present
            import asyncio
            await asyncio.sleep(2)  # Wait for page to load
            dismissed = await self._dismiss_cookie_popup(browser)

            title = await browser.title()
            current_url = await browser.url()

            cookie_msg = " (cookie popup dismissed)" if dismissed else ""

            return ToolResult(
                f"Browser started{host_info} and navigated to: {current_url}{cookie_msg}\n"
                f"Page title: {title}\n\n"
                f"Use grocery_browser_see to view the page structure, "
                f"grocery_browser_fill/click to interact."
            )
        except Exception as e:
            return ToolResult(f"Failed to start browser: {e}", is_error=True)

    @llm_callable(description="Get a structured view of the current page (inputs, buttons, links, content sections).")
    async def grocery_browser_see(self, session: "Session" = None) -> ToolResult:
        """See the current page structure."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            vision = await state._browser.see()
            url = await state._browser.url()
            title = await state._browser.title()

            lines = [
                f"**URL:** {url}",
                f"**Title:** {title}",
                "",
            ]

            # Format the PageVision structure
            lines.append(json.dumps(vision, indent=2, default=str))

            return ToolResult("\n".join(lines))
        except Exception as e:
            return ToolResult(f"Failed to see page: {e}", is_error=True)

    @llm_callable(
        description="Get all input fields on the current page.",
    )
    async def grocery_browser_inputs(self, session: "Session" = None) -> ToolResult:
        """List all input fields."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            inputs = await state._browser.inputs()
            if not inputs:
                return ToolResult("No input fields found on this page.")

            lines = ["**Input fields:**\n"]
            for inp in inputs:
                inp_dict = json.loads(inp) if isinstance(inp, str) else inp
                idx = inp_dict.get("index", "?")
                name = inp_dict.get("name") or inp_dict.get("id") or inp_dict.get("placeholder") or "(unnamed)"
                inp_type = inp_dict.get("input_type", "text")
                lines.append(f"  [{idx}] {name} (type={inp_type})")

            lines.append("\nUse grocery_browser_fill(index=N, value='...') to fill an input.")
            return ToolResult("\n".join(lines))
        except Exception as e:
            return ToolResult(f"Failed to get inputs: {e}", is_error=True)

    @llm_callable(
        description="Get all buttons on the current page.",
    )
    async def grocery_browser_buttons(self, session: "Session" = None) -> ToolResult:
        """List all buttons."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            buttons = await state._browser.buttons()
            if not buttons:
                return ToolResult("No buttons found on this page.")

            lines = ["**Buttons:**\n"]
            for btn in buttons:
                btn_dict = json.loads(btn) if isinstance(btn, str) else btn
                idx = btn_dict.get("index", "?")
                text = btn_dict.get("text", "(no text)")[:50]
                lines.append(f"  [{idx}] {text}")

            lines.append("\nUse grocery_browser_click_button(index=N) to click a button.")
            return ToolResult("\n".join(lines))
        except Exception as e:
            return ToolResult(f"Failed to get buttons: {e}", is_error=True)

    @llm_callable(
        description="Fill an input field by index (from grocery_browser_inputs).",
        params={
            "index": Param(int, "Input index from grocery_browser_inputs"),
            "value": Param(str, "Value to enter"),
        }
    )
    async def grocery_browser_fill(
        self,
        index: int,
        value: str,
        session: "Session" = None
    ) -> ToolResult:
        """Fill an input field."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            await state._browser.set_input(index, value)
            return ToolResult(f"Filled input [{index}] with: {value}")
        except Exception as e:
            return ToolResult(f"Failed to fill input: {e}", is_error=True)

    @llm_callable(
        description="Click a button by index (from grocery_browser_buttons).",
        params={
            "index": Param(int, "Button index from grocery_browser_buttons"),
        }
    )
    async def grocery_browser_click_button(
        self,
        index: int,
        session: "Session" = None
    ) -> ToolResult:
        """Click a button."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            await state._browser.click_button(index)
            # Wait a moment for page to react
            import asyncio
            await asyncio.sleep(0.5)
            url = await state._browser.url()
            return ToolResult(f"Clicked button [{index}]. Current URL: {url}")
        except Exception as e:
            return ToolResult(f"Failed to click button: {e}", is_error=True)

    @llm_callable(
        description="Click an element by CSS selector.",
        params={
            "selector": Param(str, "CSS selector (e.g., '#login-btn', '.submit-button')"),
        }
    )
    async def grocery_browser_click(
        self,
        selector: str,
        session: "Session" = None
    ) -> ToolResult:
        """Click an element by selector."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            await state._browser.click(selector)
            import asyncio
            await asyncio.sleep(0.5)
            url = await state._browser.url()
            return ToolResult(f"Clicked '{selector}'. Current URL: {url}")
        except Exception as e:
            return ToolResult(f"Failed to click: {e}", is_error=True)

    @llm_callable(
        description="Navigate to a URL.",
        params={
            "url": Param(str, "URL to navigate to"),
        }
    )
    async def grocery_browser_goto(
        self,
        url: str,
        session: "Session" = None
    ) -> ToolResult:
        """Navigate to a URL."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            await state._browser.goto(url)
            title = await state._browser.title()
            current_url = await state._browser.url()
            return ToolResult(f"Navigated to: {current_url}\nTitle: {title}")
        except Exception as e:
            return ToolResult(f"Failed to navigate: {e}", is_error=True)

    @llm_callable(
        description="Search on the grocery site using the search box.",
        params={
            "query": Param(str, "Search query"),
        }
    )
    async def grocery_browser_search(
        self,
        query: str,
        session: "Session" = None
    ) -> ToolResult:
        """Use the site's search functionality."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            await state._browser.search(query)
            import asyncio
            await asyncio.sleep(1.5)  # Wait for search results
            url = await state._browser.url()
            title = await state._browser.title()
            return ToolResult(f"Searched for: {query}\nCurrent URL: {url}\nTitle: {title}")
        except Exception as e:
            return ToolResult(f"Failed to search: {e}", is_error=True)

    @llm_callable(
        description="Take a screenshot of the current page. Returns PNG image data.",
    )
    async def grocery_browser_screenshot(self, session: "Session" = None) -> ToolResult:
        """Take a screenshot."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            png_bytes = await state._browser.screenshot()
            # Save to temp file and return path
            import tempfile
            import os
            fd, path = tempfile.mkstemp(suffix=".png", prefix="grocery_")
            with os.fdopen(fd, "wb") as f:
                f.write(png_bytes)
            return ToolResult(f"Screenshot saved to: {path}\n(You can view this file)")
        except Exception as e:
            return ToolResult(f"Failed to take screenshot: {e}", is_error=True)

    @llm_callable(
        description="""Find stores near a location. Uses the store locator.
Returns store IDs, names, addresses, and distances.
Use the store ID with grocery_set_store to select your store.""",
        params={
            "location": Param(str, "Postal code, city name, or address (e.g., 'V5K 0A1', 'Vancouver BC')"),
        }
    )
    async def grocery_browser_find_stores(
        self,
        location: str,
        session: "Session" = None
    ) -> ToolResult:
        """Find stores near a location using the browser."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            import asyncio

            # Navigate to store locator
            url = "https://www.realcanadiansuperstore.ca/store-locator"
            await state._browser.goto(url)
            await asyncio.sleep(2)

            # Find the location search input and fill it
            fill_js = f'''
            (function() {{
                var input = document.querySelector('input[placeholder*="address"], input[placeholder*="Address"], input[type="search"]');
                if (input) {{
                    input.value = "{location}";
                    input.dispatchEvent(new Event("input", {{bubbles: true}}));
                    return true;
                }}
                return false;
            }})()
            '''
            filled = await state._browser.execute_js(fill_js)

            if not filled:
                return ToolResult("Could not find location search input on store locator page.", is_error=True)

            # Wait for autocomplete/results
            await asyncio.sleep(2)

            # Press Enter or click search button to submit
            submit_js = '''
            (function() {
                // Try to find and click a search/submit button
                var btn = document.querySelector('button[type="submit"], button[aria-label*="search"], button[aria-label*="Search"]');
                if (btn) { btn.click(); return "clicked button"; }
                // Or trigger Enter key on the input
                var input = document.querySelector('input[placeholder*="address"], input[placeholder*="Address"], input[type="search"]');
                if (input) {
                    input.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", code: "Enter", keyCode: 13, bubbles: true}));
                    return "pressed enter";
                }
                return "no action";
            })()
            '''
            await state._browser.execute_js(submit_js)

            # Wait for results to load
            await asyncio.sleep(3)

            # Extract store info via JavaScript
            stores_js = """
            (function() {
                var stores = [];
                // Look for store cards/items
                var cards = document.querySelectorAll('[data-testid="store-card"], .store-card, [class*="StoreCard"], [class*="store-item"]');
                if (cards.length === 0) {
                    // Try a more generic approach
                    cards = document.querySelectorAll('[data-store-id], [data-location-id]');
                }
                cards.forEach(function(card, idx) {
                    var storeId = card.getAttribute('data-store-id') || card.getAttribute('data-location-id') || '';
                    var name = card.querySelector('[class*="name"], [class*="Name"], h2, h3')?.textContent?.trim() || '';
                    var address = card.querySelector('[class*="address"], [class*="Address"]')?.textContent?.trim() || '';
                    var distance = card.querySelector('[class*="distance"], [class*="Distance"]')?.textContent?.trim() || '';

                    // Try to extract store ID from any link containing /store-locator/
                    if (!storeId) {
                        var link = card.querySelector('a[href*="/store-locator/"]');
                        if (link) {
                            var match = link.href.match(/store-locator\\/([0-9]+)/);
                            if (match) storeId = match[1];
                        }
                    }

                    if (name || storeId) {
                        stores.push({idx: idx, id: storeId, name: name, address: address, distance: distance});
                    }
                });

                // Fallback: look for structured data in page
                if (stores.length === 0) {
                    var scripts = document.querySelectorAll('script[type="application/ld+json"]');
                    scripts.forEach(function(script) {
                        try {
                            var data = JSON.parse(script.textContent);
                            if (Array.isArray(data)) {
                                data.forEach(function(item) {
                                    if (item['@type'] === 'LocalBusiness' || item['@type'] === 'Store') {
                                        stores.push({
                                            id: item.identifier || '',
                                            name: item.name || '',
                                            address: item.address?.streetAddress || '',
                                            distance: ''
                                        });
                                    }
                                });
                            }
                        } catch(e) {}
                    });
                }

                return stores;
            })()
            """

            result = await state._browser.execute_js(stores_js)

            if not result or (isinstance(result, list) and len(result) == 0):
                # Take a screenshot for debugging
                return ToolResult(
                    f"No stores found. The page may have a different structure.\\n"
                    f"Current URL: {await state._browser.url()}\\n"
                    f"Try using grocery_browser_see to examine the page."
                )

            # Format results
            lines = [f"Stores near '{location}':\\n"]
            for store in result[:10]:  # Limit to 10 results
                store_id = store.get('id', 'N/A')
                name = store.get('name', 'Unknown')
                address = store.get('address', '')
                distance = store.get('distance', '')

                line = f"  **{name}** (ID: {store_id})"
                if distance:
                    line += f" - {distance}"
                if address:
                    line += f"\\n    {address}"
                lines.append(line)

            lines.append(f"\\nUse grocery_set_store(store_id='<ID>', banner='{state.banner}') to select a store.")

            return ToolResult("\\n".join(lines))

        except Exception as e:
            return ToolResult(f"Failed to find stores: {e}", is_error=True)

    @llm_callable(
        description="Execute JavaScript on the current page.",
        params={
            "script": Param(str, "JavaScript code to execute"),
        }
    )
    async def grocery_browser_js(
        self,
        script: str,
        session: "Session" = None
    ) -> ToolResult:
        """Execute JavaScript."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            result = await state._browser.execute_js(script)
            return ToolResult(f"Result: {json.dumps(result, indent=2)}")
        except Exception as e:
            return ToolResult(f"Failed to execute JS: {e}", is_error=True)

    @llm_callable(
        description="Get the current cart item count.",
    )
    async def grocery_browser_cart_count(self, session: "Session" = None) -> ToolResult:
        """Get cart count from the browser."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            import re
            result = await state._browser.execute_js(
                'document.querySelector("[aria-label*=cart]")?.getAttribute("aria-label") || "0"'
            )
            # Parse "N items in cart" -> N
            count = 0
            if "items" in str(result):
                match = re.search(r'(\d+)\s*items?', str(result))
                if match:
                    count = int(match.group(1))

            return ToolResult(f"Cart contains {count} item(s)")
        except Exception as e:
            return ToolResult(f"Failed to get cart count: {e}", is_error=True)

    @llm_callable(
        description="Find 'Add to cart' buttons on the current page and list products.",
    )
    async def grocery_browser_list_products(self, session: "Session" = None) -> ToolResult:
        """List available products with their add-to-cart buttons."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            buttons_raw = await state._browser.buttons()
            buttons = json.loads(buttons_raw) if isinstance(buttons_raw, str) else buttons_raw

            # Find "Add to cart" buttons
            products = []
            for btn in buttons:
                text = btn.get('text', '') or ''
                if 'Add' in text and 'cart' in text:
                    # Extract product name from "Add X to cart"
                    name = text.replace('Add ', '').replace(' to cart', '')
                    products.append({
                        "index": btn['index'],
                        "name": name,
                        "button_text": text
                    })

            if not products:
                return ToolResult("No 'Add to cart' buttons found. Are you on a search results or product page?")

            lines = [f"Found {len(products)} products:"]
            for p in products[:20]:  # Limit to 20
                lines.append(f"  [{p['index']}] {p['name']}")

            lines.append("\nUse grocery_browser_add_product(index) to add a product to cart.")
            return ToolResult("\n".join(lines))
        except Exception as e:
            return ToolResult(f"Failed to list products: {e}", is_error=True)

    @llm_callable(
        description="Add a product to cart by clicking its 'Add to cart' button.",
        params={
            "index": Param(int, "Button index from grocery_browser_list_products"),
        }
    )
    async def grocery_browser_add_product(
        self,
        index: int,
        session: "Session" = None
    ) -> ToolResult:
        """Add a product to cart by button index."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            import asyncio
            import re

            # Get cart count before
            before = await state._browser.execute_js(
                'document.querySelector("[aria-label*=cart]")?.getAttribute("aria-label") || "0"'
            )
            before_count = 0
            if "items" in str(before):
                match = re.search(r'(\d+)\s*items?', str(before))
                if match:
                    before_count = int(match.group(1))

            # Dismiss any popup that might have appeared
            await self._dismiss_cookie_popup(state._browser)

            # Click the button
            await state._browser.click_button(index)
            await asyncio.sleep(2)  # Wait for cart to update

            # Get cart count after
            after = await state._browser.execute_js(
                'document.querySelector("[aria-label*=cart]")?.getAttribute("aria-label") || "0"'
            )
            after_count = 0
            if "items" in str(after):
                match = re.search(r'(\d+)\s*items?', str(after))
                if match:
                    after_count = int(match.group(1))

            if after_count > before_count:
                return ToolResult(f"Added to cart! Cart now has {after_count} item(s) (was {before_count})")
            else:
                return ToolResult(f"Clicked button {index}. Cart count: {after_count} (may need to check manually)")
        except Exception as e:
            return ToolResult(f"Failed to add product: {e}", is_error=True)

    @llm_callable(description="Close the browser.")
    async def grocery_browser_stop(self, session: "Session" = None) -> ToolResult:
        """Stop the browser."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running.")

        try:
            await state._browser.disconnect()
            state._browser = None
            return ToolResult("Browser closed.")
        except Exception as e:
            state._browser = None
            return ToolResult(f"Browser closed (with error: {e})")
