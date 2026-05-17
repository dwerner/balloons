set shell := ["bash", "-cu"]

default:
    just --list

gen:
    source .venv/bin/activate
    python -m codegen.generate_rust

fmt:
    cd balloons-rs
    cargo +nightly fmt --all

clippy:
    cd balloons-rs
    cargo clippy --workspace --all-targets --all-features

build: gen
    source .venv/bin/activate
    cd balloons-rs/crates/balloons-py && maturin develop --release
