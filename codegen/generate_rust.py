#!/usr/bin/env python3
"""Generate Rust schema code from Python dataclasses.

Usage:
    python -m codegen.generate_rust

This generates:
    balloons-rs/crates/balloons-core/src/generated/schema.rs
    balloons-rs/crates/balloons-core/src/generated/mod.rs

The generated code is committed to the repo. If the Python schema changes,
re-run this generator and commit the updated Rust code.

Domain entities are marked with @rust_schema decorator in their original
module (e.g., models.py). Import those modules here to trigger registration.
"""

import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from codegen.rust_schema import RustSchemaRegistry, generate_rust_struct, collect_rust_imports


def get_rust_output_dir() -> Path:
    """Get the path to the Rust generated directory."""
    return project_root / "balloons-rs" / "crates" / "balloons-core" / "src" / "generated"


def generate_header(imports: set[str]) -> str:
    """Generate the file header comment and imports."""
    timestamp = datetime.now().isoformat()
    header = f'''//! AUTO-GENERATED CODE - DO NOT EDIT
//!
//! Generated from Python domain entities marked with @rust_schema.
//! Source: models.py and other domain modules
//! Generated: {timestamp}
//!
//! To regenerate:
//!     python -m codegen.generate_rust
//!
//! To add new types, add @rust_schema decorator to dataclasses in your domain modules.

use serde::{{Deserialize, Serialize}};
'''

    # Add conditional imports
    if "std::collections::HashMap" in imports:
        header += "use std::collections::HashMap;\n"

    return header


def generate_mod_rs() -> str:
    """Generate the mod.rs file."""
    return '''//! AUTO-GENERATED CODE - DO NOT EDIT
//!
//! Generated Rust types from Python domain entities.
//! To regenerate: python -m codegen.generate_rust

mod schema;

pub use schema::*;
'''


def main():
    """Generate Rust code from registered Python schemas."""
    # Import modules containing @rust_schema decorated classes
    # Add imports here for any module with types to export to Rust
    try:
        import storage_schema  # Storage DTOs for Rust
    except ImportError as e:
        print(f"Error: Could not import storage_schema: {e}")
        sys.exit(1)

    classes = RustSchemaRegistry.get_all()
    if not classes:
        print("No classes registered with @rust_schema")
        print("Add @rust_schema decorator to dataclasses in storage_schema.py")
        sys.exit(1)

    print(f"Generating Rust code for {len(classes)} classes:")
    for cls in classes:
        print(f"  - {cls.__name__}")

    # Collect all imports
    all_imports: set[str] = set()
    for cls in classes:
        all_imports.update(collect_rust_imports(cls))

    # Generate schema.rs
    parts = [generate_header(all_imports)]
    for cls in classes:
        parts.append("")
        parts.append(generate_rust_struct(cls))

    schema_content = "\n".join(parts) + "\n"

    # Write files
    output_dir = get_rust_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    schema_path = output_dir / "schema.rs"
    schema_path.write_text(schema_content)
    print(f"\nGenerated: {schema_path}")

    mod_path = output_dir / "mod.rs"
    mod_path.write_text(generate_mod_rs())
    print(f"Generated: {mod_path}")

    print("\nDone! Run 'cargo check' to verify the generated code.")


if __name__ == "__main__":
    main()
