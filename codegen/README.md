# Codegen: Python to Rust Schema Generation

Generates Rust struct definitions from Python dataclasses.

## Usage

```bash
cd /path/to/balloons
python -m codegen.generate_rust
```

## How It Works

1. **Mark dataclasses** with `@rust_schema` decorator in `storage_schema.py`
2. **Run generator** to produce Rust code in `balloons-rs/crates/balloons-core/src/generated/`
3. **Commit generated code** - the generated files are version controlled

## Files

| File | Purpose |
|------|---------|
| `rust_schema.py` | `@rust_schema` decorator, type mapping, struct generation |
| `generate_rust.py` | CLI generator script |
| `../storage_schema.py` | Storage DTOs marked with `@rust_schema` |

## Type Mapping

| Python | Rust |
|--------|------|
| `str` | `String` |
| `int` | `i64` |
| `float` | `f64` |
| `bool` | `bool` |
| `Optional[T]` | `Option<T>` |
| `list[T]` | `Vec<T>` |
| `dict` | `serde_json::Value` |
| `dict[K, V]` | `HashMap<K, V>` |
| Nested dataclass | Struct name |

## Adding New Types

1. Add `@rust_schema` decorator to your dataclass in `storage_schema.py`:

```python
from codegen import rust_schema

@rust_schema
@dataclass
class MyNewType:
    id: str
    count: int
    data: Optional[dict] = None
```

2. Regenerate:

```bash
python -m codegen.generate_rust
```

3. Verify and commit:

```bash
cd balloons-rs && cargo check
git add balloons-rs/crates/balloons-core/src/generated/
```

## Generated Output

The generator creates:

- `balloons-rs/crates/balloons-core/src/generated/schema.rs` - Struct definitions
- `balloons-rs/crates/balloons-core/src/generated/mod.rs` - Module exports

Example output:

```rust
//! AUTO-GENERATED CODE - DO NOT EDIT

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TurnData {
    pub id: String,
    pub role: String,
    pub content_block: serde_json::Value,
    pub tokens: i64,
    // ...
}
```

## Why Generate?

- **Single source of truth**: Python defines the schema
- **No drift**: Changes to Python automatically propagate to Rust
- **Type safety**: Rust compiler validates the generated code
- **Flexibility**: Complex types (like `ContentBlock` variants) serialize as JSON
