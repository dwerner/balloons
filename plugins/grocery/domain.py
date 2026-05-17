"""Canadian Grocery domain plugin.

Provides grocery shopping capabilities using reverse-engineered APIs:
- PC Express (Loblaw): Superstore, No Frills, Loblaws, Zehrs, etc.
- SaveOn Foods

Maintains a local cart that can be exported for injection into the real site.
"""

import json
import os
import aiohttp
from dataclasses import dataclass, field
from pathlib import Path
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


# --- Chain Adapter Protocol ---
# Each grocery chain has different URL patterns, DOM structure, and product extraction logic.
# Adapters encapsulate these differences behind a common interface.

from typing import Protocol


class GroceryChainAdapter(Protocol):
    """Protocol for grocery chain adapters.

    Each adapter handles chain-specific:
    - URL construction (home, search, product detail)
    - Product extraction from search results
    - Store selection
    - Cart interactions
    """

    @property
    def chain(self) -> GroceryChain:
        """The chain this adapter handles."""
        ...

    def get_home_url(self, store_id: str | None, banner: str) -> str:
        """Get the home page URL for this chain."""
        ...

    def get_search_url(self, query: str, store_id: str | None, banner: str) -> str:
        """Get the search results URL for a query."""
        ...

    def get_product_url(self, code: str, store_id: str | None, banner: str) -> str:
        """Get the product detail page URL."""
        ...

    def get_product_extraction_js(self, limit: int = 20) -> str:
        """Get JavaScript code to extract products from search results page.

        Returns JS that produces an array of objects with:
        - code: product code/ID
        - name: product name
        - price: price text
        - unit_price: unit price text (e.g., "$0.15/100ml")
        - image_url: product image URL
        - href: link to product detail
        - in_cart: quantity in cart (if visible)
        - add_button_index: index of add-to-cart button
        - increase_button_index: index of increase quantity button
        - decrease_button_index: index of decrease quantity button
        """
        ...

    def get_store_select_url(self, store_id: str, banner: str) -> str | None:
        """Get URL to select/set a store. Returns None if not URL-based."""
        ...


class PCExpressAdapter:
    """Adapter for PC Express / Loblaw brands.

    Supports: Superstore, No Frills, Loblaws, Zehrs, Fortinos, Provigo, Maxi, Valu-mart
    """

    # Domain mapping for each banner
    DOMAINS = {
        "superstore": "www.realcanadiansuperstore.ca",
        "nofrills": "www.nofrills.ca",
        "loblaws": "www.loblaws.ca",
        "zehrs": "www.zehrs.ca",
        "fortinos": "www.fortinos.ca",
        "provigo": "www.provigo.ca",
        "maxi": "www.maxi.ca",
        "valumart": "www.valumart.ca",
        "independentcitymarket": "www.yourindependentgrocer.ca",
        "yourindependentgrocer": "www.yourindependentgrocer.ca",
    }

    @property
    def chain(self) -> GroceryChain:
        return GroceryChain.PCEXPRESS

    def _get_domain(self, banner: str) -> str:
        return self.DOMAINS.get(banner, "www.realcanadiansuperstore.ca")

    def get_home_url(self, store_id: str | None, banner: str) -> str:
        domain = self._get_domain(banner)
        return f"https://{domain}/"

    def get_search_url(self, query: str, store_id: str | None, banner: str) -> str:
        import urllib.parse
        domain = self._get_domain(banner)
        encoded_query = urllib.parse.quote(query)
        return f"https://{domain}/search?search-bar={encoded_query}"

    def get_product_url(self, code: str, store_id: str | None, banner: str) -> str:
        domain = self._get_domain(banner)
        # PC Express uses /en/p/{slug}/{code}_EA pattern
        return f"https://{domain}/en/p/product/{code}_EA"

    def get_store_select_url(self, store_id: str, banner: str) -> str:
        domain = self._get_domain(banner)
        return f"https://{domain}/en/store-locator/details/{store_id}"

    def get_product_extraction_js(self, limit: int = 20) -> str:
        """PC Express product extraction from search results.

        Uses .chakra-linkbox cards with product images from loblaws CDN.
        """
        return f'''(function() {{
            let cards = document.querySelectorAll('.chakra-linkbox');
            let results = [];
            let allBtns = Array.from(document.querySelectorAll('button'));
            let found = 0;

            for (let i = 0; i < cards.length && found < {limit}; i++) {{
                let card = cards[i];
                // Check for product image
                let img = card.querySelector('img');
                if (!img) continue;
                // Product images are from loblaws CDN with /products/ path or PCX in path
                let isProduct = img.src.includes('/products/') ||
                               img.src.includes('digital.loblaws') ||
                               img.src.includes('PCX');
                if (!isProduct) continue;

                let link = card.querySelector('a[href*="/p/"]');
                let priceEl = card.querySelector('[data-testid*="price"]');
                // Extract product code from URL patterns:
                // /products/20962518/ or /PCX/20962518_EA/
                let codeMatch = img.src.match(/\\/products\\/([0-9]+)/) ||
                               img.src.match(/PCX\\/([0-9_A-Z]+)/);

                // Check if item is in cart by looking for "X product in cart" text
                let cardText = card.innerText;
                let inCartMatch = cardText.match(/(\\d+)\\s+[^\\n]+\\s+in cart/i);
                let inCart = inCartMatch ? parseInt(inCartMatch[1]) : 0;

                // Find buttons - either "Add to cart" or increase/decrease
                let addBtn = Array.from(card.querySelectorAll('button')).find(
                    b => b.textContent.includes('Add') && b.textContent.includes('to cart')
                );
                let increaseBtn = Array.from(card.querySelectorAll('button')).find(
                    b => b.textContent.includes('Increase')
                );
                let decreaseBtn = Array.from(card.querySelectorAll('button')).find(
                    b => b.textContent.includes('Decrease')
                );

                let addBtnIndex = addBtn ? allBtns.indexOf(addBtn) : -1;
                let increaseBtnIndex = increaseBtn ? allBtns.indexOf(increaseBtn) : -1;
                let decreaseBtnIndex = decreaseBtn ? allBtns.indexOf(decreaseBtn) : -1;

                results.push({{
                    code: codeMatch ? codeMatch[1] : null,
                    href: link?.getAttribute('href'),
                    imgSrc: img.src,
                    alt: img.alt,
                    price: priceEl?.textContent,
                    inCart: inCart,
                    addButtonIndex: addBtnIndex,
                    increaseButtonIndex: increaseBtnIndex,
                    decreaseButtonIndex: decreaseBtnIndex
                }});
                found++;
            }}
            return results;
        }})()'''


class SaveOnAdapter:
    """Adapter for SaveOn Foods.

    SaveOn uses a different URL structure with /sm/{mode}/rsid/{store_id}/ paths.
    Modes: 'delivery', 'pickup', 'planning'
    """

    DOMAIN = "www.saveonfoods.com"

    @property
    def chain(self) -> GroceryChain:
        return GroceryChain.SAVEON

    def get_home_url(self, store_id: str | None, banner: str) -> str:
        # Load mode from config
        config = _load_plugin_config()
        mode = config.get("saveon_mode", "delivery")
        store = store_id or config.get("saveon_store_id", "1982")
        return f"https://{self.DOMAIN}/sm/{mode}/rsid/{store}"

    def get_search_url(self, query: str, store_id: str | None, banner: str) -> str:
        import urllib.parse
        config = _load_plugin_config()
        mode = config.get("saveon_mode", "delivery")
        store = store_id or config.get("saveon_store_id", "1982")
        encoded_query = urllib.parse.quote(query)
        return f"https://{self.DOMAIN}/sm/{mode}/rsid/{store}/results?q={encoded_query}"

    def get_product_url(self, code: str, store_id: str | None, banner: str) -> str:
        config = _load_plugin_config()
        mode = config.get("saveon_mode", "delivery")
        store = store_id or config.get("saveon_store_id", "1982")
        # SaveOn URLs: /sm/{mode}/rsid/{store_id}/product/{slug}-id-{code}
        # We don't know the slug, but the site redirects based on code
        return f"https://{self.DOMAIN}/sm/{mode}/rsid/{store}/product/item-id-{code}"

    def get_store_select_url(self, store_id: str, banner: str) -> str | None:
        # SaveOn doesn't use a store selection URL - it's embedded in the URL path
        return None

    def get_product_extraction_js(self, limit: int = 20) -> str:
        """SaveOn Foods product extraction from search results.

        Uses [class*="ProductCardWrapper"] cards with structured text content.
        """
        return f'''(function() {{
            var cards = document.querySelectorAll('[class*="ProductCardWrapper"]');
            var products = [];
            var allBtns = Array.from(document.querySelectorAll('button'));
            var found = 0;

            cards.forEach(function(card, i) {{
                if (found >= {limit}) return;

                var img = card.querySelector('img');
                var link = card.querySelector('a[href*="/product/"]');
                var texts = card.innerText.split('\\n').filter(function(t) {{ return t.trim(); }});

                // Extract price (matches $X.XX pattern)
                var priceMatch = texts.find(function(t) {{ return t.match(/^\\$[\\d.]+$/); }});
                // Extract unit price (contains /100)
                var unitMatch = texts.find(function(t) {{ return t.includes('/100'); }});
                // Extract product code from URL
                var codeMatch = link && link.href ? link.href.match(/-id-(\\d+)/) : null;

                // Check for in-cart status
                var inCartMatch = card.innerText.match(/(\\d+)\\s+in\\s+cart/i);
                var inCart = inCartMatch ? parseInt(inCartMatch[1]) : 0;

                // Find buttons
                var addBtn = Array.from(card.querySelectorAll('button')).find(function(b) {{
                    return b.textContent.toLowerCase().includes('add to cart');
                }});
                var increaseBtn = Array.from(card.querySelectorAll('button')).find(function(b) {{
                    return b.textContent.includes('+') || b.textContent.toLowerCase().includes('increase');
                }});
                var decreaseBtn = Array.from(card.querySelectorAll('button')).find(function(b) {{
                    return b.textContent.includes('-') || b.textContent.toLowerCase().includes('decrease');
                }});

                products.push({{
                    code: codeMatch ? codeMatch[1] : null,
                    href: link ? link.getAttribute('href') : null,
                    imgSrc: img ? img.src : null,
                    alt: img ? img.alt : '',
                    price: priceMatch || null,
                    unitPrice: unitMatch || null,
                    inCart: inCart,
                    addButtonIndex: addBtn ? allBtns.indexOf(addBtn) : -1,
                    increaseButtonIndex: increaseBtn ? allBtns.indexOf(increaseBtn) : -1,
                    decreaseButtonIndex: decreaseBtn ? allBtns.indexOf(decreaseBtn) : -1
                }});
                found++;
            }});

            return products;
        }})()'''


def _get_adapter(chain: GroceryChain) -> GroceryChainAdapter:
    """Get the appropriate adapter for a grocery chain."""
    if chain == GroceryChain.SAVEON:
        return SaveOnAdapter()
    else:
        return PCExpressAdapter()


# --- Data Models for Price Tracking ---

@dataclass
class ProductData:
    """Harvested product information."""
    code: str
    name: str
    brand: str | None = None
    size: str | None = None
    image_url: str | None = None
    nutrition: dict | None = None  # Nutrition facts from detail page
    ingredients: str | None = None  # Ingredients text from detail page
    updated: str = ""  # ISO date of last update

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "brand": self.brand,
            "size": self.size,
            "image_url": self.image_url,
            "nutrition": self.nutrition,
            "ingredients": self.ingredients,
            "updated": self.updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProductData":
        return cls(
            code=data["code"],
            name=data["name"],
            brand=data.get("brand"),
            size=data.get("size"),
            image_url=data.get("image_url"),
            nutrition=data.get("nutrition"),
            ingredients=data.get("ingredients"),
            updated=data.get("updated", ""),
        )


@dataclass
class PriceRecord:
    """A price observation for a product at a specific store and date."""
    code: str  # Product code
    store_id: str
    banner: str
    date: str  # YYYY-MM-DD
    price: float
    unit_price: float | None = None  # e.g., $/100ml
    unit_price_text: str | None = None  # e.g., "$0.15/100ml"
    on_sale: bool = False
    was_price: float | None = None  # Original price if on sale

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "store_id": self.store_id,
            "banner": self.banner,
            "date": self.date,
            "price": self.price,
            "unit_price": self.unit_price,
            "unit_price_text": self.unit_price_text,
            "on_sale": self.on_sale,
            "was_price": self.was_price,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PriceRecord":
        return cls(
            code=data["code"],
            store_id=data["store_id"],
            banner=data["banner"],
            date=data["date"],
            price=data["price"],
            unit_price=data.get("unit_price"),
            unit_price_text=data.get("unit_price_text"),
            on_sale=data.get("on_sale", False),
            was_price=data.get("was_price"),
        )


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

# Persistent storage for per-session data
_storage: JsonFileStorage | None = None

# Plugin-wide config (persists across reloads)
_plugin_config: dict[str, Any] | None = None
_plugin_config_path: Path | None = None


def _get_plugin_config_path() -> Path:
    """Get the path to the plugin config file."""
    global _plugin_config_path
    if _plugin_config_path is None:
        config_dir = Path.home() / ".balloons" / "plugins" / "grocery"
        config_dir.mkdir(parents=True, exist_ok=True)
        _plugin_config_path = config_dir / "config.json"
    return _plugin_config_path


def _load_plugin_config() -> dict[str, Any]:
    """Load plugin-wide config from disk."""
    global _plugin_config
    if _plugin_config is not None:
        return _plugin_config

    config_path = _get_plugin_config_path()
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                _plugin_config = json.load(f)
        except (json.JSONDecodeError, IOError):
            _plugin_config = {}
    else:
        _plugin_config = {}
    return _plugin_config


def _save_plugin_config() -> None:
    """Save plugin-wide config to disk."""
    global _plugin_config
    if _plugin_config is None:
        return

    config_path = _get_plugin_config_path()
    try:
        with open(config_path, "w") as f:
            json.dump(_plugin_config, f, indent=2)
    except IOError:
        pass  # Best effort


def _get_storage() -> JsonFileStorage:
    global _storage
    if _storage is None:
        _storage = JsonFileStorage("grocery")
    return _storage


# --- Product & Price Data Storage ---

_products_cache: dict[str, ProductData] | None = None
_prices_cache: list[PriceRecord] | None = None


def _get_data_dir() -> Path:
    """Get the data directory for products and prices."""
    data_dir = Path.home() / ".balloons" / "plugins" / "grocery" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _load_products() -> dict[str, ProductData]:
    """Load all products from JSONL file."""
    global _products_cache
    if _products_cache is not None:
        return _products_cache

    _products_cache = {}
    products_file = _get_data_dir() / "products.jsonl"
    if products_file.exists():
        try:
            with open(products_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        product = ProductData.from_dict(data)
                        _products_cache[product.code] = product
        except (json.JSONDecodeError, IOError):
            pass
    return _products_cache


def _save_product(product: ProductData) -> None:
    """Save or update a product in the JSONL file."""
    global _products_cache
    products = _load_products()

    # Update cache
    products[product.code] = product
    _products_cache = products

    # Rewrite file (could optimize with append-only + compaction)
    products_file = _get_data_dir() / "products.jsonl"
    try:
        with open(products_file, "w") as f:
            for p in products.values():
                f.write(json.dumps(p.to_dict()) + "\n")
    except IOError:
        pass


def _load_prices() -> list[PriceRecord]:
    """Load all price records from JSONL file."""
    global _prices_cache
    if _prices_cache is not None:
        return _prices_cache

    _prices_cache = []
    prices_file = _get_data_dir() / "prices.jsonl"
    if prices_file.exists():
        try:
            with open(prices_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        price = PriceRecord.from_dict(data)
                        _prices_cache.append(price)
        except (json.JSONDecodeError, IOError):
            pass
    return _prices_cache


def _save_price(price: PriceRecord) -> None:
    """Append a price record to the JSONL file.

    Deduplicates: only one price per (code, store_id, banner, date).
    """
    global _prices_cache
    prices = _load_prices()

    # Check if we already have a price for this combination today
    key = (price.code, price.store_id, price.banner, price.date)
    existing_idx = None
    for i, p in enumerate(prices):
        if (p.code, p.store_id, p.banner, p.date) == key:
            existing_idx = i
            break

    if existing_idx is not None:
        # Update existing
        prices[existing_idx] = price
    else:
        # Append new
        prices.append(price)

    _prices_cache = prices

    # Rewrite file
    prices_file = _get_data_dir() / "prices.jsonl"
    try:
        with open(prices_file, "w") as f:
            for p in prices:
                f.write(json.dumps(p.to_dict()) + "\n")
    except IOError:
        pass


def _get_price_history(code: str, store_id: str | None = None, banner: str | None = None) -> list[PriceRecord]:
    """Get price history for a product, optionally filtered by store/banner."""
    prices = _load_prices()
    result = []
    for p in prices:
        if p.code != code:
            continue
        if store_id and p.store_id != store_id:
            continue
        if banner and p.banner != banner:
            continue
        result.append(p)
    # Sort by date
    result.sort(key=lambda x: x.date)
    return result


def _harvest_product_price(
    code: str,
    name: str,
    store_id: str,
    banner: str,
    price: float,
    unit_price: float | None = None,
    unit_price_text: str | None = None,
    on_sale: bool = False,
    was_price: float | None = None,
    brand: str | None = None,
    size: str | None = None,
    image_url: str | None = None,
) -> None:
    """Harvest product and price data from a page view."""
    today = datetime.now().strftime("%Y-%m-%d")

    # Update/create product record
    products = _load_products()
    if code in products:
        product = products[code]
        # Update basic fields but preserve nutrition/ingredients
        product.name = name
        if brand:
            product.brand = brand
        if size:
            product.size = size
        if image_url:
            product.image_url = image_url
        product.updated = today
    else:
        product = ProductData(
            code=code,
            name=name,
            brand=brand,
            size=size,
            image_url=image_url,
            updated=today,
        )
    _save_product(product)

    # Record price
    price_record = PriceRecord(
        code=code,
        store_id=store_id,
        banner=banner,
        date=today,
        price=price,
        unit_price=unit_price,
        unit_price_text=unit_price_text,
        on_sale=on_sale,
        was_price=was_price,
    )
    _save_price(price_record)


def _harvest_nutrition(code: str, nutrition: dict | None, ingredients: str | None) -> None:
    """Update a product with nutrition facts and ingredients from detail page."""
    products = _load_products()
    if code not in products:
        return

    product = products[code]
    if nutrition:
        product.nutrition = nutrition
    if ingredients:
        product.ingredients = ingredients
    product.updated = datetime.now().strftime("%Y-%m-%d")
    _save_product(product)


def _get_state(session_id: str) -> GroceryState:
    """Get or create state for a session."""
    if session_id not in _session_states:
        # Load defaults from plugin config
        config = _load_plugin_config()
        state = GroceryState()
        state.browser_host = config.get("browser_host", "local")
        # Load default store if configured
        if config.get("store_id"):
            state.store_id = config["store_id"]
            state.banner = config.get("banner", "superstore")
            state.chain = BANNER_TO_CHAIN.get(state.banner, GroceryChain.PCEXPRESS)
        _session_states[session_id] = state
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

    def on_unload(self) -> None:
        """Close all browser instances when domain is unloaded."""
        import asyncio

        # Close any active browser sessions
        for session_id, state in list(_session_states.items()):
            if state._browser is not None:
                try:
                    # Get or create an event loop
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(state._browser.disconnect())
                    except RuntimeError:
                        # No running loop, create one
                        asyncio.run(state._browser.disconnect())
                except Exception:
                    pass  # Best effort cleanup
                finally:
                    state._browser = None

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

    @ws_expose
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
        save_default: bool = True,
        session: "Session" = None
    ) -> ToolResult:
        """Set the store for shopping."""
        state = _get_state(session.id)
        state.store_id = store_id
        state.banner = banner
        state.chain = BANNER_TO_CHAIN.get(banner, GroceryChain.PCEXPRESS)

        # Save as default if requested
        saved_msg = ""
        if save_default:
            # Reload config from disk to avoid stale cache issues
            global _plugin_config
            _plugin_config = None
            config = _load_plugin_config()

            if state.chain == GroceryChain.SAVEON:
                # SaveOn uses separate config keys - preserves PC Express settings
                config["saveon_store_id"] = store_id
            else:
                # PC Express stores
                config["store_id"] = store_id
                config["banner"] = banner
            _save_plugin_config()
            saved_msg = " (saved as default)"

        banner_name = ALL_BANNERS.get(banner, banner)
        chain_name = "SaveOn Foods" if state.chain == GroceryChain.SAVEON else "PC Express"
        return ToolResult(
            f"Store set to {banner_name} (ID: {store_id}, Chain: {chain_name}){saved_msg}.\n"
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

    @llm_callable(description="Show the current store setting. Prices vary by store so this is important.")
    async def grocery_store_info(self, session: "Session" = None) -> ToolResult:
        """Show current store info."""
        state = _get_state(session.id)

        if not state.store_id:
            return ToolResult(
                "**No store set.**\n\n"
                "Use `grocery_set_store(store_id='...', banner='...')` to set a store.\n"
                "Or use `grocery_browser_find_stores(location='V5K 0A1')` to search for stores."
            )

        banner_name = ALL_BANNERS.get(state.banner, state.banner)
        chain_name = "SaveOn Foods" if state.chain == GroceryChain.SAVEON else "PC Express"

        lines = ["**Current Store:**\n"]
        lines.append(f"  Store: **{banner_name}** #{state.store_id}")
        lines.append(f"  Chain: {chain_name}")
        lines.append(f"  Banner code: `{state.banner}`")

        # Show price data stats for this store
        prices = _load_prices()
        store_prices = [p for p in prices if p.store_id == state.store_id and p.banner == state.banner]
        if store_prices:
            dates = set(p.date for p in store_prices)
            products = set(p.code for p in store_prices)
            lines.append(f"\n**Price Data:**")
            lines.append(f"  {len(products)} products tracked")
            lines.append(f"  {len(store_prices)} price records")
            lines.append(f"  Date range: {min(dates)} to {max(dates)}")

        return ToolResult("\n".join(lines))

    # Alias for consistency with namespace
    @llm_callable(
        description="""Set the store to shop at. Required before shopping.
Same as grocery_set_store but follows the grocery_store_* naming convention.""",
        params={
            "store_id": Param(str, "Store ID/number"),
            "banner": Param(str, "Store banner (default: superstore)", required=False),
        }
    )
    async def grocery_store_select(
        self,
        store_id: str,
        banner: str = "superstore",
        session: "Session" = None
    ) -> ToolResult:
        """Set store (alias for grocery_set_store)."""
        return await self.grocery_set_store(store_id=store_id, banner=banner, save_default=True, session=session)

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

    @ws_expose
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

    @ws_expose
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

        # Persist to plugin config so it survives reloads
        plugin_config = _load_plugin_config()
        plugin_config["browser_host"] = host
        _save_plugin_config()

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
Use 'local' for headless on this machine, or a supervisor host name for a remote display.
This setting persists across plugin reloads.""",
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

        # Persist to plugin config so it survives reloads
        plugin_config = _load_plugin_config()
        plugin_config["browser_host"] = host
        _save_plugin_config()

        host_config = config.hosts[host]
        if host_config.type == "local":
            return ToolResult(f"Browser host set to **local** (saved). Will run headless on this machine.")
        else:
            return ToolResult(
                f"Browser host set to **{host}** (saved) ({host_config.user}@{host_config.host}).\n"
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

    async def _dismiss_medallia_survey(self, browser) -> bool:
        """Dismiss Medallia survey popups (PC Express uses these)."""
        try:
            result = await browser.execute_js(
                '(function() { '
                'var iframes = document.querySelectorAll("iframe[id*=kampyleForm]"); '
                'if (iframes.length > 0) { '
                '  iframes.forEach(function(f) { '
                '    if (f.parentElement) f.parentElement.remove(); '
                '  }); '
                '  return true; '
                '} '
                'return false; '
                '})()'
            )
            return result == "true" or result is True
        except Exception:
            pass
        return False

    async def _dismiss_any_modal(self, browser) -> bool:
        """Dismiss any modal/dialog that might be blocking interaction.

        Handles:
        - "Shop the offer" promotional modals
        - Chakra UI modals (the site uses Chakra)
        - Generic dialogs with Close/X buttons
        """
        try:
            result = await browser.execute_js(
                '(function() { '
                'var closed = []; '
                # 1. Look for Chakra modal overlay and close button
                'var chakraModal = document.querySelector("[class*=\\"chakra-modal\\"]"); '
                'if (chakraModal) { '
                '  var closeBtn = chakraModal.querySelector("button"); '
                '  var btns = Array.from(chakraModal.querySelectorAll("button")); '
                '  var close = btns.find(function(b) { return b.textContent.trim() === "Close"; }); '
                '  if (close) { close.click(); closed.push("chakra-close"); } '
                '  else if (closeBtn) { closeBtn.click(); closed.push("chakra-first-btn"); } '
                '} '
                # 2. Look for role="dialog" elements
                'var dialogs = document.querySelectorAll("[role=\\"dialog\\"]"); '
                'dialogs.forEach(function(d) { '
                '  var closeBtn = d.querySelector("[aria-label*=\\"close\\"], [aria-label*=\\"Close\\"], button:first-child"); '
                '  if (closeBtn) { closeBtn.click(); closed.push("dialog"); } '
                '}); '
                # 3. Look for any button with exact text "Close"
                'if (closed.length === 0) { '
                '  var btns = Array.from(document.querySelectorAll("button")); '
                '  var closeBtn = btns.find(function(b) { return b.textContent.trim() === "Close"; }); '
                '  if (closeBtn) { closeBtn.click(); closed.push("close-btn"); } '
                '} '
                # 4. Press Escape key as fallback
                'if (closed.length === 0) { '
                '  document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", code: "Escape", keyCode: 27, bubbles: true})); '
                '  closed.push("escape"); '
                '} '
                'return closed.length > 0 ? closed.join(",") : "none"; '
                '})()'
            )
            return result and str(result) != "none" and "none" not in str(result)
        except Exception:
            pass
        return False

    async def _dismiss_pc_overlays(self, browser) -> bool:
        """Dismiss PC Express overlays: smartbanners, mealplanner chat, etc."""
        try:
            result = await browser.execute_js(
                '(function() { '
                'let removed = 0; '
                # Smartbanners (mobile app promo)
                'document.querySelectorAll(".smartbanner-wrapper, .smartbanner-container, .smartbanner").forEach(function(el) { el.remove(); removed++; }); '
                # PC Mealplanner AI chat widget (island block)
                'document.querySelectorAll("[class*=\\"mealPlannerChatBot\\"], [class*=\\"Mealplanner\\"], [data-testid*=\\"meal-planner\\"]").forEach(function(el) { el.remove(); removed++; }); '
                # Generic modals/overlays that might block
                'document.querySelectorAll("[class*=\\"overlay\\"][class*=\\"modal\\"], [class*=\\"popup\\"][class*=\\"chat\\"]").forEach(function(el) { el.remove(); removed++; }); '
                'return removed > 0; '
                '})()'
            )
            return result == "true" or result is True or (isinstance(result, bool) and result)
        except Exception:
            pass
        return False

    async def _dismiss_popups(self, browser) -> dict:
        """Dismiss all known popups. Returns dict of what was dismissed."""
        dismissed = {}
        dismissed["cookie"] = await self._dismiss_cookie_popup(browser)
        dismissed["survey"] = await self._dismiss_medallia_survey(browser)
        dismissed["modal"] = await self._dismiss_any_modal(browser)
        dismissed["overlays"] = await self._dismiss_pc_overlays(browser)
        return dismissed

    @ws_expose
    @llm_callable(
        description="""Launch a browser and navigate to a grocery site.
Use this to start an interactive shopping session where you can see and interact with the page.
Uses the host selected via grocery_browser_set_host (defaults to local).

For local: headless=True (default) runs invisibly, headless=False shows GUI window.
For remote hosts: always shows GUI on that display.

Browser types:
- 'chrome': Standard Chrome via chromedriver (works for PC Express)
- 'firefox': Firefox via geckodriver
- 'undetected': Chrome with anti-detection patches (required for SaveOn Foods)""",
        params={
            "url": Param(str, "URL to navigate to (default: based on store banner)", required=False),
            "headless": Param(bool, "Run without visible window (default: True for local, False for remote)", required=False),
            "webdriver_url": Param(str, "Override: direct WebDriver URL (ignores host setting)", required=False),
            "browser_type": Param(str, "Browser type: 'chrome', 'firefox', or 'undetected' (default: auto based on chain)", required=False),
        }
    )
    async def grocery_browser_start(
        self,
        url: str | None = None,
        headless: bool = False,
        webdriver_url: str | None = None,
        browser_type: str | None = None,
        session: "Session" = None
    ) -> ToolResult:
        """Launch browser for grocery shopping."""
        from supervisor_config import get_supervisor_config

        state = _get_state(session.id)

        if state._browser is not None:
            return ToolResult("Browser already running. Use grocery_browser_stop first.", is_error=True)

        try:
            import balloons_py as bs
        except ImportError:
            return ToolResult(
                "balloons_py not available. Browser automation requires the Rust extension.",
                is_error=True
            )

        # Get the adapter for this chain
        adapter = _get_adapter(state.chain)

        # Determine URL based on chain/banner using adapter
        if url is None:
            url = adapter.get_home_url(state.store_id, state.banner)

        # Determine webdriver URL from host setting if not overridden
        host_info = ""
        is_remote = False
        if webdriver_url is None and state.browser_host != "local":
            config = get_supervisor_config()
            host = config.hosts.get(state.browser_host)
            if host and host.type == "ssh" and host.host:
                webdriver_url = f"http://{host.host}:4444"
                host_info = f" on {state.browser_host}"
                is_remote = True

        # headless parameter controls GUI vs headless:
        # - headless=False (default) → show GUI window
        # - headless=True → run without visible window
        #
        # For local without a display, we force headless=True since there's no GUI to show.
        # Remote hosts and direct webdriver_url can run either mode.
        if not is_remote and webdriver_url is None and not headless:
            # Local with no webdriver and wanting GUI - but local has no display
            headless = True

        try:
            # Create config - supports chrome or firefox
            # Default to chrome for compatibility (SaveOn uses undetected-chromedriver proxy)
            actual_browser_type = browser_type or "chrome"
            browser_config = bs.BrowserConfig(
                browser_type=actual_browser_type,
                headless=headless,
                webdriver_url=webdriver_url,
            )
            browser = bs.Browser(browser_config)
            await browser.connect()
            await browser.goto(url)

            state._browser = browser

            # Dismiss cookie popup if present
            import asyncio
            await asyncio.sleep(2)  # Wait for page to load
            dismissed = await self._dismiss_cookie_popup(browser)

            # Auto-set store from config if configured
            store_set_msg = ""
            plugin_config = _load_plugin_config()

            # For PC Express, we need to navigate to store-locator and confirm
            # For SaveOn, the store is embedded in the URL (already done via adapter)
            store_select_url = adapter.get_store_select_url(
                plugin_config.get("store_id", ""),
                plugin_config.get("banner", state.banner)
            )

            if store_select_url and state.chain == GroceryChain.PCEXPRESS:
                try:
                    store_id = plugin_config["store_id"]

                    # Navigate to store page and click YES to set as preferred
                    await browser.goto(store_select_url)
                    await asyncio.sleep(3)  # Wait longer for page to fully load

                    # Click YES to confirm store - try multiple times
                    yes_clicked = None
                    for _ in range(3):
                        yes_clicked = await browser.execute_js('''(function() {
                            var yesBtn = Array.from(document.querySelectorAll('button, a')).find(
                                el => el.textContent.trim() === 'YES' || el.textContent.trim() === 'Yes'
                            );
                            if (yesBtn) { yesBtn.click(); return "clicked"; }
                            return "not_found";
                        })()''')
                        if yes_clicked and ("clicked" in str(yes_clicked)):
                            break
                        await asyncio.sleep(1)

                    # Handle result - may be string or JSON-encoded string
                    if yes_clicked and ("clicked" in str(yes_clicked)):
                        await asyncio.sleep(2)  # Wait for store to be set
                        store_set_msg = f" (store {store_id} set as default)"

                    # Navigate back to main page
                    await browser.goto(url)
                    await asyncio.sleep(1)
                except Exception as e:
                    # Log but don't fail
                    store_set_msg = f" (store setting failed: {e})"
            elif state.chain == GroceryChain.SAVEON:
                # SaveOn store is already in the URL
                saveon_store = plugin_config.get("saveon_store_id")
                if saveon_store:
                    store_set_msg = f" (SaveOn store {saveon_store})"

            title = await browser.title()
            current_url = await browser.url()

            cookie_msg = " (cookie popup dismissed)" if dismissed else ""

            return ToolResult(
                f"Browser started{host_info} and navigated to: {current_url}{cookie_msg}{store_set_msg}\n"
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

    @ws_expose
    @llm_callable(
        description="Search on the grocery site. Uses direct URL navigation for reliability.",
        params={
            "query": Param(str, "Search query"),
        }
    )
    async def grocery_browser_search(
        self,
        query: str,
        session: "Session" = None
    ) -> ToolResult:
        """Use the site's search functionality via URL navigation."""
        import asyncio

        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            # Get adapter and build search URL
            adapter = _get_adapter(state.chain)
            search_url = adapter.get_search_url(query, state.store_id, state.banner)

            await state._browser.goto(search_url)
            await asyncio.sleep(2)  # Wait for search results to load

            # Dismiss any popups that appeared
            await self._dismiss_popups(state._browser)

            url = await state._browser.url()
            title = await state._browser.title()
            return ToolResult(f"Searched for: {query}\nCurrent URL: {url}\nTitle: {title}")
        except Exception as e:
            return ToolResult(f"Failed to search: {e}", is_error=True)

    @ws_expose
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

            # Handle case where result is returned as JSON string
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    pass

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
        description="Dismiss popups (cookie consent, surveys, etc.) that might block interaction.",
    )
    async def grocery_browser_dismiss_popups(self, session: "Session" = None) -> ToolResult:
        """Dismiss blocking popups."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            dismissed = await self._dismiss_popups(state._browser)
            parts = []
            if dismissed.get("cookie"):
                parts.append("cookie consent")
            if dismissed.get("survey"):
                parts.append("Medallia survey")
            if dismissed.get("modal"):
                parts.append("modal/dialog")
            if dismissed.get("overlays"):
                parts.append("overlays")
            if parts:
                return ToolResult(f"Dismissed: {', '.join(parts)}")
            else:
                return ToolResult("No popups found to dismiss.")
        except Exception as e:
            return ToolResult(f"Failed to dismiss popups: {e}", is_error=True)

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

    @ws_expose
    @llm_callable(
        description="""Get the contents of your cart (tracked locally).
Shows items added via grocery_browser_add_product this session.
Note: This is our local tracking - the actual site cart may differ if items were added/removed elsewhere.""",
    )
    async def grocery_browser_get_cart(self, session: "Session" = None) -> ToolResult:
        """Show locally tracked cart contents."""
        state = _get_state(session.id)

        if not state.cart:
            # Also check browser cart count for comparison
            browser_count = 0
            if state._browser:
                try:
                    import re
                    result = await state._browser.execute_js(
                        'document.querySelector("[aria-label*=cart]")?.getAttribute("aria-label") || "0"'
                    )
                    if "items" in str(result):
                        match = re.search(r'(\d+)\s*items?', str(result))
                        if match:
                            browser_count = int(match.group(1))
                except Exception:
                    pass

            if browser_count > 0:
                return ToolResult(
                    f"Local cart is empty, but browser shows {browser_count} item(s).\n"
                    "Items may have been added before tracking started."
                )
            return ToolResult("Cart is empty.")

        lines = ["**Your Cart (locally tracked):**\n"]
        subtotal = 0.0
        total_items = 0

        for item in state.cart.values():
            item_total = item.price * item.quantity
            subtotal += item_total
            total_items += item.quantity

            name = item.name
            if item.brand:
                name = f"{item.brand} {name}"
            if item.size:
                name += f" ({item.size})"

            if item.price > 0:
                lines.append(f"  • {item.quantity}x **{name}** - ${item.price:.2f} ea = ${item_total:.2f}")
            else:
                lines.append(f"  • {item.quantity}x **{name}** - price unknown")

        lines.append(f"\n**Total:** {total_items} item(s)")
        if subtotal > 0:
            lines.append(f"**Subtotal:** ${subtotal:.2f}")

        # Compare with browser count
        if state._browser:
            try:
                import re
                result = await state._browser.execute_js(
                    'document.querySelector("[aria-label*=cart]")?.getAttribute("aria-label") || "0"'
                )
                browser_count = 0
                if "items" in str(result):
                    match = re.search(r'(\d+)\s*items?', str(result))
                    if match:
                        browser_count = int(match.group(1))
                if browser_count != total_items:
                    lines.append(f"\n⚠️ Browser shows {browser_count} items (tracking may be out of sync)")
            except Exception:
                pass

        return ToolResult("\n".join(lines))

    @llm_callable(
        description="Clear the locally tracked cart (does not affect the actual site cart).",
    )
    async def grocery_browser_clear_local_cart(self, session: "Session" = None) -> ToolResult:
        """Clear local cart tracking."""
        state = _get_state(session.id)
        count = len(state.cart)
        state.cart.clear()
        return ToolResult(f"Cleared local cart tracking ({count} items removed).")

    @llm_callable(
        description="""Sync local cart with what's visible on the current page.
Reads cart quantities from product cards on the page and updates local tracking.
Call this after navigating to a search results page to sync cart state.""",
    )
    async def grocery_browser_sync_cart(self, session: "Session" = None) -> ToolResult:
        """Sync local cart with page state."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            # Extract cart quantities from all product cards on page
            js_code = '''(function() {
                let cards = document.querySelectorAll('.chakra-linkbox');
                let items = [];
                cards.forEach(function(card) {
                    let img = card.querySelector('img[src*="digital.loblaws"]');
                    if (!img) return;
                    let codeMatch = img.src.match(/PCX\\/([0-9_A-Z]+)/);
                    if (!codeMatch) return;

                    let cardText = card.innerText;
                    let inCartMatch = cardText.match(/(\\d+)\\s+[^\\n]+\\s+in cart/i);
                    let qty = inCartMatch ? parseInt(inCartMatch[1]) : 0;

                    if (qty > 0) {
                        let alt = img.alt || '';
                        let priceEl = card.querySelector('[data-testid*="price"]');
                        items.push({
                            code: codeMatch[1],
                            name: alt.split(',')[0],
                            qty: qty,
                            price: priceEl?.textContent || ''
                        });
                    }
                });
                return items;
            })()'''

            result = await state._browser.execute_js(js_code)
            if isinstance(result, str):
                result = json.loads(result)

            if not result:
                # No items in cart visible on page
                return ToolResult("No items in cart found on current page.")

            # Update local cart state
            import re
            synced = []
            for item in result:
                code = item.get('code')
                if not code:
                    continue

                # Parse price
                price_text = item.get('price', '')
                price = 0.0
                price_match = re.search(r'\$?([\d.]+)', price_text)
                if price_match:
                    price = float(price_match.group(1))

                if code in state.cart:
                    state.cart[code].quantity = item['qty']
                else:
                    state.cart[code] = CartItem(
                        product_code=code,
                        name=item.get('name', 'Unknown'),
                        price=price,
                        unit="each",
                        quantity=item['qty'],
                        chain="pcexpress",
                    )
                synced.append(f"{item['qty']}x {item.get('name', code)}")

            return ToolResult(f"Synced cart from page:\\n" + "\\n".join(f"  • {s}" for s in synced))
        except Exception as e:
            return ToolResult(f"Failed to sync cart: {e}", is_error=True)

    @ws_expose
    @llm_callable(
        description="Get structured product data from the current search results page.",
    )
    async def grocery_browser_get_products(
        self,
        limit: int = 20,
        session: "Session" = None
    ) -> ToolResult:
        """Extract structured product data from search results.

        Returns product code, name, brand, size, price, unit price, image URL, and href.
        """
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            # Get adapter and use chain-specific extraction JS
            adapter = _get_adapter(state.chain)
            js_code = adapter.get_product_extraction_js(limit)

            raw_products = await state._browser.execute_js(js_code)

            # Handle case where result is returned as JSON string
            if isinstance(raw_products, str):
                raw_products = json.loads(raw_products)

            if not raw_products:
                return ToolResult("No products found. Are you on a search results page?")

            # Parse product data - handles both PC Express and SaveOn formats
            import re
            products = []
            for p in raw_products:
                alt = p.get('alt', '')

                # Determine format based on chain
                if state.chain == GroceryChain.SAVEON:
                    # SaveOn format: "Brand - Product Name, Size"
                    # Example: "Island Farms - 2% Milk, 4 Litre"
                    name_part = alt

                    # Try to extract size from end (after comma or as last part)
                    size_match = re.search(r',?\s*([\d.]+\s*(?:Litre|litre|L|l|ml|mL|Gram|gram|g|kg|Kilogram|kilogram|oz|lb))\s*$', alt, re.I)
                    size = size_match.group(1) if size_match else None
                    if size:
                        name_part = alt[:alt.lower().rfind(size.lower())].rstrip(', ')

                    # SaveOn returns unitPrice directly from JS
                    unit_price = p.get('unitPrice')

                    # Price comes directly from SaveOn JS extraction
                    price_text = p.get('price') or ''
                    price = price_text if price_text else None
                    was_price = None
                    on_sale = False
                else:
                    # PC Express format: "Brand Name Size, $X.XX/unit"
                    # Example: "Dairyland 2% Regular Milk 4 l, $0.15/100ml"

                    unit_price_match = re.search(r',\s*(\$[\d.]+/\w+)$', alt)
                    unit_price = unit_price_match.group(1) if unit_price_match else None

                    # Remove unit price from name
                    name_part = re.sub(r',\s*\$[\d.]+/\w+$', '', alt)

                    # Try to extract size (e.g., "4 l", "400 g", "1.5 l")
                    size_match = re.search(r'\s+([\d.]+\s*(?:l|L|ml|mL|g|kg|oz|lb))\s*$', name_part)
                    size = size_match.group(1) if size_match else None

                    # Remove size from name
                    if size:
                        name_part = name_part[:name_part.rfind(size)].strip()

                    # Parse price - handle sale prices
                    price_text = p.get('price') or ''
                    price = None
                    was_price = None
                    on_sale = False

                    if price_text and 'sale' in price_text.lower():
                        on_sale = True
                        sale_match = re.search(r'sale[:\s]*(\$[\d.]+)', price_text, re.I)
                        was_match = re.search(r'(?:was|formerly)[:\s]*(\$[\d.]+)', price_text, re.I)
                        if sale_match:
                            price = sale_match.group(1)
                        if was_match:
                            was_price = was_match.group(1)
                    else:
                        price_match = re.search(r'(\$[\d.]+)', price_text)
                        if price_match:
                            price = price_match.group(1)

                products.append({
                    'code': p.get('code'),
                    'name': name_part,
                    'size': size,
                    'price': price,
                    'was_price': was_price,
                    'on_sale': on_sale,
                    'unit_price': unit_price,
                    'image_url': p.get('imgSrc'),
                    'href': p.get('href'),
                    'in_cart': p.get('inCart', 0),
                    'add_button_index': p.get('addButtonIndex', -1),
                    'increase_button_index': p.get('increaseButtonIndex', -1),
                    'decrease_button_index': p.get('decreaseButtonIndex', -1),
                })

            # Store for UI access
            state.last_search_results = products

            # Harvest product/price data if store is set
            if state.store_id:
                import re as re_module
                for p in products:
                    if not p.get('code'):
                        continue
                    # Parse price to float
                    price_val = None
                    was_price_val = None
                    unit_price_val = None
                    if p.get('price'):
                        price_match = re_module.search(r'\$([\d.]+)', p['price'])
                        if price_match:
                            try:
                                price_val = float(price_match.group(1))
                            except ValueError:
                                pass
                    if p.get('was_price'):
                        was_match = re_module.search(r'\$([\d.]+)', p['was_price'])
                        if was_match:
                            try:
                                was_price_val = float(was_match.group(1))
                            except ValueError:
                                pass
                    if p.get('unit_price'):
                        unit_match = re_module.search(r'\$([\d.]+)', p['unit_price'])
                        if unit_match:
                            try:
                                unit_price_val = float(unit_match.group(1))
                            except ValueError:
                                pass

                    if price_val is not None:
                        _harvest_product_price(
                            code=p['code'],
                            name=p.get('name', ''),
                            store_id=state.store_id,
                            banner=state.banner,
                            price=price_val,
                            unit_price=unit_price_val,
                            unit_price_text=p.get('unit_price'),
                            on_sale=p.get('on_sale', False),
                            was_price=was_price_val,
                            size=p.get('size'),
                            image_url=p.get('image_url'),
                        )

            # Format for LLM
            lines = [f"Found {len(products)} products:\n"]
            for i, p in enumerate(products):
                price_str = p['price'] or 'N/A'
                if p['on_sale'] and p['was_price']:
                    price_str = f"**{p['price']}** (was {p['was_price']})"

                # Show cart status prominently
                cart_qty = p.get('in_cart', 0)
                if cart_qty > 0:
                    lines.append(f"{i+1}. **{p['name']}** 🛒 **{cart_qty} in cart**")
                else:
                    lines.append(f"{i+1}. **{p['name']}**")

                if p['size']:
                    lines.append(f"   Size: {p['size']}")
                lines.append(f"   Price: {price_str}")
                if p['unit_price']:
                    lines.append(f"   Unit: {p['unit_price']}")
                lines.append(f"   Code: {p['code']}")

                # Show product URL for direct navigation
                if p['href']:
                    lines.append(f"   URL: {p['href']}")

                # Show appropriate buttons based on cart status
                if cart_qty > 0:
                    if p['increase_button_index'] >= 0:
                        lines.append(f"   [+] button: [{p['increase_button_index']}]  [-] button: [{p['decrease_button_index']}]")
                else:
                    if p['add_button_index'] >= 0:
                        lines.append(f"   Add button: [{p['add_button_index']}]")
                lines.append("")

            return ToolResult("\n".join(lines))
        except Exception as e:
            return ToolResult(f"Failed to get products: {e}", is_error=True)

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
        description="""Get detailed product info including nutrition facts.
Navigate to a product page first, then call this to extract full details.""",
    )
    async def grocery_browser_get_product_detail(self, session: "Session" = None) -> ToolResult:
        """Extract detailed product info from current product page."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            import asyncio

            # Dismiss overlays first
            await self._dismiss_popups(state._browser)

            # Extract product info via JS
            js_code = '''(function() {
                let result = {};

                // Basic product info - use specific PC Express selectors
                // Name is in h1.product-name__item--name
                let title = document.querySelector('h1.product-name__item--name, h1[class*="product-name"]');
                result.name = title?.textContent?.trim() || '';

                // Brand is in .product-name__item--brand (sibling of name)
                let brand = document.querySelector('.product-name__item--brand');
                result.brand = brand?.textContent?.trim() || '';

                // Price - look for the main product price, not carousel items
                let priceContainer = document.querySelector('[class*="product-details-page"] [data-testid*="price"], [class*="product-price"]');
                result.price = priceContainer?.textContent?.trim() || '';

                // Product code from URL
                let urlMatch = window.location.pathname.match(/\\/p\\/([A-Z0-9_]+)/);
                result.code = urlMatch ? urlMatch[1] : '';

                // Description
                let desc = document.querySelector('[class*="product-description"], [class*="ProductDescription"]');
                result.description = desc?.textContent?.trim()?.substring(0, 500) || '';

                // Expand nutrition section if needed
                let nutritionBody = document.querySelector('.product-details-page-nutrition-info__body');
                if (nutritionBody && window.getComputedStyle(nutritionBody).display === 'none') {
                    nutritionBody.style.display = 'block';
                }

                // Nutrition facts
                if (nutritionBody) {
                    result.nutrition_raw = nutritionBody.innerText?.substring(0, 1500) || '';

                    // Try to parse structured nutrition
                    let servingSize = nutritionBody.innerText.match(/Serving Size[:\\s]+([^\\n]+)/i);
                    result.serving_size = servingSize ? servingSize[1].trim() : '';

                    let calories = nutritionBody.innerText.match(/Calories[:\\s]+(\\d+)/i);
                    result.calories = calories ? parseInt(calories[1]) : null;

                    // Ingredients
                    let ingredients = nutritionBody.innerText.match(/Ingredients[:\\s]+([^*]+)/i);
                    result.ingredients = ingredients ? ingredients[1].trim() : '';
                }

                // Main product image
                let img = document.querySelector('[data-testid*="product-image"] img, [class*="product-image"] img');
                result.image_url = img?.src || '';

                return result;
            })()''';

            product = await state._browser.execute_js(js_code)

            # Handle case where result is returned as JSON string
            if isinstance(product, str):
                product = json.loads(product)

            if not product or not product.get('name'):
                return ToolResult(
                    "Could not extract product details. Make sure you're on a product page (URL contains /p/).",
                    is_error=True
                )

            # Harvest nutrition data
            code = product.get('code')
            if code:
                # Build nutrition dict
                nutrition = {}
                if product.get('serving_size'):
                    nutrition['serving_size'] = product['serving_size']
                if product.get('calories'):
                    nutrition['calories'] = product['calories']
                if product.get('nutrition_raw'):
                    # Parse common nutrition fields from raw text
                    import re as re_mod
                    raw = product['nutrition_raw']
                    patterns = {
                        'fat': r'Fat[:\s]+([\d.]+\s*g)',
                        'saturated_fat': r'Saturated[:\s]+([\d.]+\s*g)',
                        'carbohydrate': r'Carbohydrate[:\s]+([\d.]+\s*g)',
                        'fibre': r'Fibre[:\s]+([\d.]+\s*g)',
                        'sugars': r'Sugars[:\s]+([\d.]+\s*g)',
                        'protein': r'Protein[:\s]+([\d.]+\s*g)',
                        'sodium': r'Sodium[:\s]+([\d.]+\s*mg)',
                        'cholesterol': r'Cholesterol[:\s]+([\d.]+\s*mg)',
                    }
                    for key, pattern in patterns.items():
                        match = re_mod.search(pattern, raw, re_mod.IGNORECASE)
                        if match:
                            nutrition[key] = match.group(1)

                # Save to product database
                ingredients = product.get('ingredients')
                if nutrition or ingredients:
                    _harvest_nutrition(code, nutrition if nutrition else None, ingredients)

                # Also harvest price if store is set
                if state.store_id and product.get('price'):
                    import re as re_mod2
                    price_match = re_mod2.search(r'\$([\d.]+)', product['price'])
                    if price_match:
                        try:
                            price_val = float(price_match.group(1))
                            _harvest_product_price(
                                code=code,
                                name=product.get('name', ''),
                                store_id=state.store_id,
                                banner=state.banner,
                                price=price_val,
                                brand=product.get('brand'),
                                image_url=product.get('image_url'),
                            )
                        except ValueError:
                            pass

            # Format output
            lines = [f"# {product.get('name', 'Unknown Product')}\n"]

            if product.get('brand'):
                lines.append(f"**Brand:** {product['brand']}")
            if product.get('code'):
                lines.append(f"**Code:** {product['code']}")
            if product.get('price'):
                lines.append(f"**Price:** {product['price']}")

            if product.get('description'):
                lines.append(f"\n## Description\n{product['description']}")

            if product.get('serving_size') or product.get('calories'):
                lines.append("\n## Nutrition Facts")
                if product.get('serving_size'):
                    lines.append(f"**Serving Size:** {product['serving_size']}")
                if product.get('calories'):
                    lines.append(f"**Calories:** {product['calories']}")

            if product.get('nutrition_raw'):
                # Clean up the raw nutrition text
                lines.append(f"\n```\n{product['nutrition_raw'][:800]}\n```")

            if product.get('ingredients'):
                lines.append(f"\n## Ingredients\n{product['ingredients'][:500]}")

            return ToolResult("\n".join(lines))
        except Exception as e:
            return ToolResult(f"Failed to get product details: {e}", is_error=True)

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

            # Dismiss any popups that might block interaction
            await self._dismiss_popups(state._browser)

            # Get product name from button text before clicking
            # Buttons have text like "Add X to cart"
            product_name_result = await state._browser.execute_js(
                f'(function() {{ var btn = document.querySelectorAll("button")[{index}]; '
                f'if (btn) {{ return btn.textContent.trim(); }} return null; }})()'
            )
            product_name = None
            if product_name_result:
                # Extract name from "Add X to cart"
                name_str = str(product_name_result).replace('"', '')
                if 'Add ' in name_str and ' to cart' in name_str:
                    product_name = name_str.replace('Add ', '').replace(' to cart', '').strip()

            # Click the button using JS (more reliable than WebDriver click)
            # WebDriver click fails when elements are covered by overlays
            click_result = await state._browser.execute_js(
                f'(function() {{ var btn = document.querySelectorAll("button")[{index}]; '
                f'if (btn) {{ btn.scrollIntoView({{block: "center"}}); btn.click(); return "clicked"; }} '
                f'return "not found"; }})()'
            )
            if click_result and "not found" in str(click_result):
                return ToolResult(f"Button [{index}] not found", is_error=True)

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

            # Track in local state if add was successful
            added_successfully = after_count > before_count
            if added_successfully and product_name:
                # Try to find product details from last_search_results
                product_info = None
                for p in state.last_search_results:
                    if p.get('name') and product_name in p.get('name', ''):
                        product_info = p
                        break

                # Add to local cart tracking
                if product_info and product_info.get('code'):
                    code = product_info['code']
                    if code in state.cart:
                        state.cart[code].quantity += 1
                    else:
                        state.cart[code] = CartItem(
                            product_code=code,
                            name=product_info.get('name', product_name),
                            price=float(str(product_info.get('price', '0')).replace('$', '').split()[0] or 0),
                            unit="each",
                            quantity=1,
                            image_url=product_info.get('image_url'),
                            brand=None,
                            size=product_info.get('size'),
                            chain="pcexpress",
                        )
                else:
                    # No detailed info, just track the name
                    simple_code = f"unknown_{len(state.cart)}"
                    state.cart[simple_code] = CartItem(
                        product_code=simple_code,
                        name=product_name,
                        price=0.0,
                        unit="each",
                        quantity=1,
                        chain="pcexpress",
                    )

            if added_successfully:
                return ToolResult(f"Added to cart: {product_name or 'item'}! Cart now has {after_count} item(s) (was {before_count})")
            else:
                return ToolResult(f"Clicked button {index}. Cart count: {after_count} (may need to check manually)")
        except Exception as e:
            return ToolResult(f"Failed to add product: {e}", is_error=True)

    @llm_callable(
        description="""Increase quantity of a product already in cart.
Use the [+] button index from grocery_browser_get_products for items showing 'in cart'.""",
        params={
            "product_name": Param(str, "Product name to search for (partial match)"),
        }
    )
    async def grocery_browser_increase_quantity(
        self,
        product_name: str,
        session: "Session" = None
    ) -> ToolResult:
        """Increase quantity of a product in cart."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            import asyncio
            import re

            # Find and click the increase button by product name
            result = await state._browser.execute_js(
                f'(function() {{ '
                f'var btns = Array.from(document.querySelectorAll("button")); '
                f'var btn = btns.find(b => b.textContent.includes("Increase") && b.textContent.toLowerCase().includes("{product_name.lower()}")); '
                f'if (btn) {{ btn.scrollIntoView({{block: "center"}}); btn.click(); return "clicked"; }} '
                f'return "not found"; '
                f'}})()'
            )

            if "not found" in str(result):
                return ToolResult(f"No increase button found for '{product_name}'. Is the item in cart?", is_error=True)

            await asyncio.sleep(1.5)

            # Get updated cart count
            cart_result = await state._browser.execute_js(
                'document.querySelector("[aria-label*=cart]")?.getAttribute("aria-label") || "0"'
            )
            count = 0
            if "items" in str(cart_result):
                match = re.search(r'(\d+)\s*items?', str(cart_result))
                if match:
                    count = int(match.group(1))

            return ToolResult(f"Increased quantity for {product_name}. Cart now has {count} item(s).")
        except Exception as e:
            return ToolResult(f"Failed to increase quantity: {e}", is_error=True)

    @llm_callable(
        description="""Decrease quantity of a product in cart (or remove if qty=1).
Use the [-] button index from grocery_browser_get_products for items showing 'in cart'.""",
        params={
            "product_name": Param(str, "Product name to search for (partial match)"),
        }
    )
    async def grocery_browser_decrease_quantity(
        self,
        product_name: str,
        session: "Session" = None
    ) -> ToolResult:
        """Decrease quantity of a product in cart."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            import asyncio
            import re

            # Find and click the decrease button by product name
            result = await state._browser.execute_js(
                f'(function() {{ '
                f'var btns = Array.from(document.querySelectorAll("button")); '
                f'var btn = btns.find(b => b.textContent.includes("Decrease") && b.textContent.toLowerCase().includes("{product_name.lower()}")); '
                f'if (btn) {{ btn.scrollIntoView({{block: "center"}}); btn.click(); return "clicked"; }} '
                f'return "not found"; '
                f'}})()'
            )

            if "not found" in str(result):
                return ToolResult(f"No decrease button found for '{product_name}'. Is the item in cart?", is_error=True)

            await asyncio.sleep(1.5)

            # Get updated cart count
            cart_result = await state._browser.execute_js(
                'document.querySelector("[aria-label*=cart]")?.getAttribute("aria-label") || "0"'
            )
            count = 0
            if "items" in str(cart_result):
                match = re.search(r'(\d+)\s*items?', str(cart_result))
                if match:
                    count = int(match.group(1))

            return ToolResult(f"Decreased quantity for {product_name}. Cart now has {count} item(s).")
        except Exception as e:
            return ToolResult(f"Failed to decrease quantity: {e}", is_error=True)

    @ws_expose
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

    # =========================================================================
    # NAMESPACED TOOL ALIASES - Organized by view/context
    # =========================================================================

    # --- Search View Tools (grocery_search_*) ---

    @ws_expose
    @llm_callable(
        description="""Search for products and show results.
Returns products with name, price, cart quantity, and direct URLs for navigation.""",
        params={
            "query": Param(str, "Search query (e.g., 'milk', 'bread', 'organic eggs')"),
        }
    )
    async def grocery_search_query(
        self,
        query: str,
        session: "Session" = None
    ) -> ToolResult:
        """Search for products by query."""
        result = await self.grocery_browser_search(query=query, session=session)
        if result.is_error:
            return result
        # Follow up with product listing
        return await self.grocery_search_products(session=session)

    @ws_expose
    @llm_callable(
        description="""Get products from current search results page.
Shows products with cart quantities, prices, and URLs for direct navigation.""",
        params={
            "limit": Param(int, "Maximum products to return (default 20)", required=False),
        }
    )
    async def grocery_search_products(
        self,
        limit: int = 20,
        session: "Session" = None
    ) -> ToolResult:
        """Get products from search results (alias for grocery_browser_get_products)."""
        return await self.grocery_browser_get_products(limit=limit, session=session)

    @llm_callable(
        description="""Add product to cart from search results.
Use the button index shown in grocery_search_products.""",
        params={
            "index": Param(int, "Button index from product listing"),
        }
    )
    async def grocery_search_add_to_cart(
        self,
        index: int,
        session: "Session" = None
    ) -> ToolResult:
        """Add product to cart from search results."""
        return await self.grocery_browser_add_product(index=index, session=session)

    # --- Product Detail View Tools (grocery_product_*) ---

    @ws_expose
    @llm_callable(
        description="""Navigate to a product's detail page by URL or code.
Use the URL from grocery_search_products, or provide a product code.""",
        params={
            "url": Param(str, "Full product URL (e.g., /en/p/product-name/20962518_EA)", required=False),
            "code": Param(str, "Product code (e.g., 20962518 or 20962518_EA)", required=False),
        }
    )
    async def grocery_product_goto(
        self,
        url: str = None,
        code: str = None,
        session: "Session" = None
    ) -> ToolResult:
        """Navigate to a product detail page."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        if not url and not code:
            return ToolResult("Provide either 'url' or 'code' parameter.", is_error=True)

        try:
            if url:
                # If it's a relative URL, make it absolute
                if url.startswith('/'):
                    full_url = f"https://www.realcanadiansuperstore.ca{url}"
                else:
                    full_url = url
            else:
                # Look up URL from last search results by code
                clean_code = code.replace('_EA', '')
                found_url = None
                for p in state.last_search_results:
                    p_code = str(p.get('code', '')).replace('_EA', '')
                    if p_code == clean_code:
                        found_url = p.get('href')
                        break

                if found_url:
                    if found_url.startswith('/'):
                        full_url = f"https://www.realcanadiansuperstore.ca{found_url}"
                    else:
                        full_url = found_url
                else:
                    # Fallback: try searching for the product code
                    return ToolResult(
                        f"Product code {code} not found in recent search results.\n"
                        f"Use grocery_search_query first, or provide the full URL from search results.",
                        is_error=True
                    )

            await state._browser.goto(full_url)
            import asyncio
            await asyncio.sleep(2)

            # Dismiss any popups
            await self._dismiss_popups(state._browser)

            title = await state._browser.execute_js('document.title')
            current_url = await state._browser.execute_js('window.location.href')

            return ToolResult(
                f"Navigated to product page.\n"
                f"Title: {title}\n"
                f"URL: {current_url}\n\n"
                f"Use grocery_product_info to get details, or grocery_product_add_to_cart to add."
            )
        except Exception as e:
            return ToolResult(f"Failed to navigate to product: {e}", is_error=True)

    @ws_expose
    @llm_callable(
        description="""Get detailed product information from the current product page.
Includes name, brand, price, description, and nutrition facts.""",
    )
    async def grocery_product_info(self, session: "Session" = None) -> ToolResult:
        """Get product details from current page (alias for grocery_browser_get_product_detail)."""
        return await self.grocery_browser_get_product_detail(session=session)

    @llm_callable(
        description="""Add the current product to cart from its detail page.
Must be on a product detail page first (use grocery_product_goto).""",
        params={
            "quantity": Param(int, "Quantity to add (default 1)", required=False),
        }
    )
    async def grocery_product_add_to_cart(
        self,
        quantity: int = 1,
        session: "Session" = None
    ) -> ToolResult:
        """Add current product to cart from detail page."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            import asyncio
            import re

            # Find and click the add to cart button on product detail page
            # PC Express uses a button with just "Add" text on product pages
            js_code = '''(function() {
                // Look for add button on product detail page
                // The button text is just "Add" (not "Add to cart") on detail pages
                // But avoid "Add to List" button
                let addBtn = Array.from(document.querySelectorAll('button')).find(
                    b => {
                        let text = b.textContent.trim().toLowerCase();
                        return text === 'add' ||
                               text.includes('add to cart') ||
                               text.includes('add to bag');
                    }
                );
                if (addBtn) {
                    addBtn.scrollIntoView({block: "center"});
                    addBtn.click();
                    return "clicked";
                }
                // May already be in cart - look for increase button
                let increaseBtn = Array.from(document.querySelectorAll('button')).find(
                    b => b.textContent.includes('Increase')
                );
                if (increaseBtn) {
                    increaseBtn.click();
                    return "increased";
                }
                return "not found";
            })()'''

            for _ in range(quantity):
                result = await state._browser.execute_js(js_code)
                if "not found" in str(result):
                    return ToolResult("Add to cart button not found. Are you on a product detail page?", is_error=True)
                await asyncio.sleep(1)

            # Get cart count
            cart_result = await state._browser.execute_js(
                'document.querySelector("[aria-label*=cart]")?.getAttribute("aria-label") || "0"'
            )
            count = 0
            if "items" in str(cart_result):
                match = re.search(r'(\d+)\s*items?', str(cart_result))
                if match:
                    count = int(match.group(1))

            return ToolResult(f"Added {quantity} to cart. Cart now has {count} item(s).")
        except Exception as e:
            return ToolResult(f"Failed to add to cart: {e}", is_error=True)

    # --- Cart View Tools (grocery_cart_*) ---

    @ws_expose
    @llm_callable(description="Get the current cart item count.")
    async def grocery_cart_count(self, session: "Session" = None) -> ToolResult:
        """Get cart count (alias for grocery_browser_cart_count)."""
        return await self.grocery_browser_cart_count(session=session)

    @ws_expose
    @llm_callable(description="Show items in the locally tracked cart with prices and totals.")
    async def grocery_cart_items(self, session: "Session" = None) -> ToolResult:
        """Get cart items (alias for grocery_browser_get_cart)."""
        return await self.grocery_browser_get_cart(session=session)

    @llm_callable(
        description="""Sync local cart tracking with what's visible on the current page.
Run this after navigating to ensure cart is accurate.""",
    )
    async def grocery_cart_sync(self, session: "Session" = None) -> ToolResult:
        """Sync cart (alias for grocery_browser_sync_cart)."""
        return await self.grocery_browser_sync_cart(session=session)

    @llm_callable(description="Clear the locally tracked cart (doesn't affect the actual site cart).")
    async def grocery_cart_clear_local(self, session: "Session" = None) -> ToolResult:
        """Clear local cart (alias for grocery_browser_clear_local_cart)."""
        return await self.grocery_browser_clear_local_cart(session=session)

    @llm_callable(
        description="""Increase quantity of a product in cart by name.
Use a partial product name match.""",
        params={
            "product_name": Param(str, "Product name to search for (partial match)"),
        }
    )
    async def grocery_cart_increase(
        self,
        product_name: str,
        session: "Session" = None
    ) -> ToolResult:
        """Increase quantity (alias for grocery_browser_increase_quantity)."""
        return await self.grocery_browser_increase_quantity(product_name=product_name, session=session)

    @llm_callable(
        description="""Decrease quantity of a product in cart (or remove if qty=1).
Use a partial product name match.""",
        params={
            "product_name": Param(str, "Product name to search for (partial match)"),
        }
    )
    async def grocery_cart_decrease(
        self,
        product_name: str,
        session: "Session" = None
    ) -> ToolResult:
        """Decrease quantity (alias for grocery_browser_decrease_quantity)."""
        return await self.grocery_browser_decrease_quantity(product_name=product_name, session=session)

    @ws_expose
    @llm_callable(
        description="""Navigate to the cart review page to view cart contents and order summary.
Shows items with quantities, prices, and totals.""",
    )
    async def grocery_cart_view(self, session: "Session" = None) -> ToolResult:
        """Navigate to the cart review page."""
        state = _get_state(session.id)

        if state._browser is None:
            return ToolResult("No browser running. Use grocery_browser_start first.", is_error=True)

        try:
            import asyncio

            # Navigate to cart review page (not /cart which requires login)
            await state._browser.goto("https://www.realcanadiansuperstore.ca/en/cartReview")
            await asyncio.sleep(2)

            # Dismiss any popups
            await self._dismiss_popups(state._browser)

            # Extract cart items from product cards
            items_js = '''(function() {
                let items = [];
                let cards = document.querySelectorAll('.chakra-linkbox');
                cards.forEach(card => {
                    let img = card.querySelector('img');
                    if (!img) return;
                    // Only product images (from loblaws CDN)
                    if (!img.src.includes('loblaws') && !img.src.includes('/products/')) return;

                    let name = img.alt?.split(',')[0]?.slice(0, 50) || 'Unknown';
                    let priceEl = card.querySelector('[data-testid*="price"]');
                    let price = priceEl?.textContent?.trim() || '';

                    // Check quantity in cart
                    let qtyMatch = card.innerText.match(/(\\d+)\\s+[^\\n]+\\s+in cart/i);
                    let qty = qtyMatch ? qtyMatch[1] : '1';

                    items.push({name: name, price: price, qty: qty});
                });
                return items;
            })()'''

            items_result = await state._browser.execute_js(items_js)
            import json
            if isinstance(items_result, str):
                items_result = json.loads(items_result)
            if isinstance(items_result, str):
                items_result = json.loads(items_result)

            # Extract order summary from sidebar
            summary_js = '''(function() {
                let sidebar = document.querySelector('.cart-checkout-sidebar');
                if (!sidebar) return {itemCount: 0, subtotal: null, total: null};

                let text = sidebar.innerText;
                let subtotalMatch = text.match(/Subtotal[\\s\\n]+([\\d]+) items?[\\s\\n]+\\$([\\d.]+)/i);
                let totalMatch = text.match(/Est\\. Total[\\s\\S]*?\\$([\\d.]+)/i);

                return {
                    itemCount: subtotalMatch ? parseInt(subtotalMatch[1]) : 0,
                    subtotal: subtotalMatch ? '$' + subtotalMatch[2] : null,
                    total: totalMatch ? '$' + totalMatch[1] : null
                };
            })()'''

            summary_result = await state._browser.execute_js(summary_js)
            if isinstance(summary_result, str):
                summary_result = json.loads(summary_result)
            if isinstance(summary_result, str):
                summary_result = json.loads(summary_result)

            # Build output
            lines = ["**Cart Review**\n"]

            if summary_result and summary_result.get('itemCount', 0) > 0:
                lines.append(f"**{summary_result['itemCount']} item(s)** - Subtotal: {summary_result.get('subtotal', 'N/A')}")
                lines.append("")

            if items_result:
                lines.append("**Items:**")
                for item in items_result:
                    qty = item.get('qty', '1')
                    price = item.get('price', '')
                    lines.append(f"  • {item.get('name')} x{qty} - {price}")
                lines.append("")

            if summary_result and summary_result.get('total'):
                lines.append(f"**Est. Total:** {summary_result['total']}")

            if not items_result and (not summary_result or summary_result.get('itemCount', 0) == 0):
                return ToolResult("Cart is empty.\nUse grocery_search_query to find products and add them.")

            return ToolResult("\n".join(lines))
        except Exception as e:
            return ToolResult(f"Failed to view cart: {e}", is_error=True)

    # --- Data Tools (Price Tracking & Product Database) ---

    @llm_callable(
        description="""List harvested products from the local database.
These are products we've seen while browsing, with cached info.""",
        params={
            "query": Param(str, "Optional search query to filter products", required=False),
            "limit": Param(int, "Max products to show (default: 20)", required=False),
        }
    )
    async def grocery_data_products(
        self,
        query: str | None = None,
        limit: int = 20,
        session: "Session" = None
    ) -> ToolResult:
        """List harvested products."""
        products = _load_products()

        if not products:
            return ToolResult("No products harvested yet. Browse some products to build the database.")

        # Filter by query if provided
        results = list(products.values())
        if query:
            query_lower = query.lower()
            results = [p for p in results if query_lower in p.name.lower() or
                       (p.brand and query_lower in p.brand.lower())]

        # Sort by last updated (most recent first)
        results.sort(key=lambda x: x.updated or "", reverse=True)
        results = results[:limit]

        if not results:
            return ToolResult(f"No products matching '{query}'")

        lines = [f"**Harvested Products** ({len(results)} of {len(products)} total)\n"]
        for p in results:
            line = f"**{p.name}**"
            if p.brand:
                line = f"**{p.brand}** {p.name}"
            if p.size:
                line += f" ({p.size})"
            line += f"\n  Code: `{p.code}`"
            if p.nutrition:
                line += " | Has nutrition"
            if p.ingredients:
                line += " | Has ingredients"
            line += f" | Updated: {p.updated}"
            lines.append(line)

        return ToolResult("\n".join(lines))

    @llm_callable(
        description="""Get price history for a product.
Shows how the price has changed over time at different stores.""",
        params={
            "code": Param(str, "Product code"),
            "store_id": Param(str, "Optional: filter to specific store", required=False),
        }
    )
    async def grocery_data_prices(
        self,
        code: str,
        store_id: str | None = None,
        session: "Session" = None
    ) -> ToolResult:
        """Get price history for a product."""
        state = _get_state(session.id)

        # Get product info
        products = _load_products()
        product = products.get(code)

        # Get price history
        prices = _get_price_history(code, store_id=store_id)

        if not prices:
            if product:
                return ToolResult(f"No price history for **{product.name}** (code: {code})")
            return ToolResult(f"No price history for product code: {code}")

        lines = []
        if product:
            title = f"**{product.brand} {product.name}**" if product.brand else f"**{product.name}**"
            if product.size:
                title += f" ({product.size})"
            lines.append(title)
            lines.append(f"Code: `{code}`\n")
        else:
            lines.append(f"**Price History for {code}**\n")

        # Group by store
        by_store: dict[str, list[PriceRecord]] = {}
        for p in prices:
            key = f"{p.banner}:{p.store_id}"
            if key not in by_store:
                by_store[key] = []
            by_store[key].append(p)

        for store_key, store_prices in by_store.items():
            banner, sid = store_key.split(":", 1)
            banner_name = ALL_BANNERS.get(banner, banner)
            lines.append(f"**{banner_name} #{sid}**")

            for p in store_prices:
                sale_marker = " 🏷️ SALE" if p.on_sale else ""
                was = f" (was ${p.was_price:.2f})" if p.was_price else ""
                unit = f" ({p.unit_price_text})" if p.unit_price_text else ""
                lines.append(f"  {p.date}: **${p.price:.2f}**{unit}{sale_marker}{was}")
            lines.append("")

        # Show current store context
        if state.store_id:
            lines.append(f"_Current store: {state.banner} #{state.store_id}_")

        return ToolResult("\n".join(lines))

    @llm_callable(
        description="""Get detailed product info including nutrition facts.
Only available for products we've viewed on the detail page.""",
        params={
            "code": Param(str, "Product code"),
        }
    )
    async def grocery_data_product_detail(
        self,
        code: str,
        session: "Session" = None
    ) -> ToolResult:
        """Get detailed product info from the database."""
        products = _load_products()
        product = products.get(code)

        if not product:
            return ToolResult(f"Product {code} not found. Visit the product detail page to harvest info.")

        lines = []
        title = f"**{product.brand} {product.name}**" if product.brand else f"**{product.name}**"
        if product.size:
            title += f" ({product.size})"
        lines.append(title)
        lines.append(f"Code: `{code}`")
        lines.append(f"Last updated: {product.updated}\n")

        if product.nutrition:
            lines.append("**Nutrition Facts:**")
            for key, value in product.nutrition.items():
                lines.append(f"  {key}: {value}")
            lines.append("")

        if product.ingredients:
            lines.append("**Ingredients:**")
            lines.append(product.ingredients[:500])  # Truncate if very long
            if len(product.ingredients) > 500:
                lines.append("... (truncated)")
            lines.append("")

        if not product.nutrition and not product.ingredients:
            lines.append("_No nutrition/ingredients data. Visit the product detail page to harvest._")

        return ToolResult("\n".join(lines))

    @llm_callable(
        description="""Export all harvested product and price data.
Returns summary stats and file paths.""",
    )
    async def grocery_data_export(self, session: "Session" = None) -> ToolResult:
        """Export harvested data."""
        products = _load_products()
        prices = _load_prices()
        data_dir = _get_data_dir()

        lines = ["**Grocery Data Export**\n"]
        lines.append(f"Products: {len(products)}")
        lines.append(f"Price records: {len(prices)}")
        lines.append("")
        lines.append(f"**Data files:**")
        lines.append(f"  Products: `{data_dir / 'products.jsonl'}`")
        lines.append(f"  Prices: `{data_dir / 'prices.jsonl'}`")

        # Stats
        if prices:
            stores = set((p.store_id, p.banner) for p in prices)
            dates = set(p.date for p in prices)
            lines.append("")
            lines.append(f"**Stats:**")
            lines.append(f"  Unique stores: {len(stores)}")
            lines.append(f"  Date range: {min(dates)} to {max(dates)}")

            # Products with nutrition
            with_nutrition = sum(1 for p in products.values() if p.nutrition)
            lines.append(f"  Products with nutrition: {with_nutrition}")

        return ToolResult("\n".join(lines))

    @llm_callable(
        description="""Compare prices across stores for similar products.
Matches products by name similarity to show price differences between PC Express and SaveOn.""",
        params={
            "query": Param(str, "Product name to search for (e.g., '2% milk 4')"),
        }
    )
    async def grocery_data_compare(
        self,
        query: str,
        session: "Session" = None
    ) -> ToolResult:
        """Compare prices across stores."""
        products = _load_products()
        prices = _load_prices()

        if not products or not prices:
            return ToolResult("No data to compare. Search for products on both sites first.")

        # Find products matching the query
        query_lower = query.lower()
        matching_products = []
        for code, product in products.items():
            name_lower = product.name.lower()
            if all(term in name_lower for term in query_lower.split()):
                matching_products.append(product)

        if not matching_products:
            return ToolResult(f"No products found matching '{query}'.")

        # Get latest prices for each product
        price_by_code: dict[str, list[PriceRecord]] = {}
        for price in prices:
            if price.code not in price_by_code:
                price_by_code[price.code] = []
            price_by_code[price.code].append(price)

        # Group by chain
        pc_express_products = []
        saveon_products = []

        for product in matching_products:
            product_prices = price_by_code.get(product.code, [])
            if not product_prices:
                continue

            # Get latest price for each store
            latest_by_store = {}
            for p in sorted(product_prices, key=lambda x: x.date, reverse=True):
                key = (p.store_id, p.banner)
                if key not in latest_by_store:
                    latest_by_store[key] = p

            for (store_id, banner), price in latest_by_store.items():
                entry = {
                    "product": product,
                    "price": price,
                }
                if banner == "saveon":
                    saveon_products.append(entry)
                else:
                    pc_express_products.append(entry)

        lines = [f"**Price Comparison: '{query}'**\n"]

        if pc_express_products:
            lines.append("**PC Express:**")
            for entry in sorted(pc_express_products, key=lambda x: x["price"].price):
                p = entry["product"]
                pr = entry["price"]
                size = f" ({p.size})" if p.size else ""
                lines.append(f"  **${pr.price:.2f}** - {p.name}{size}")
                if pr.unit_price_text:
                    lines.append(f"    {pr.unit_price_text} | Store #{pr.store_id}")
            lines.append("")

        if saveon_products:
            lines.append("**SaveOn Foods:**")
            for entry in sorted(saveon_products, key=lambda x: x["price"].price):
                p = entry["product"]
                pr = entry["price"]
                size = f" ({p.size})" if p.size else ""
                lines.append(f"  **${pr.price:.2f}** - {p.name}{size}")
                if pr.unit_price_text:
                    lines.append(f"    {pr.unit_price_text} | Store #{pr.store_id}")
            lines.append("")

        # Summary comparison
        if pc_express_products and saveon_products:
            pc_min = min(e["price"].price for e in pc_express_products)
            saveon_min = min(e["price"].price for e in saveon_products)
            diff = saveon_min - pc_min
            pct = (diff / pc_min) * 100 if pc_min > 0 else 0

            lines.append("**Summary:**")
            if diff > 0:
                lines.append(f"  PC Express is **${abs(diff):.2f} cheaper** ({abs(pct):.0f}% less)")
            elif diff < 0:
                lines.append(f"  SaveOn is **${abs(diff):.2f} cheaper** ({abs(pct):.0f}% less)")
            else:
                lines.append("  Same price at both stores")

        return ToolResult("\n".join(lines))
