set shell := ["bash", "-cu"]

uv := "uv"
py := uv + " run"

default:
    just --list

gen:
    {{py}} python -m codegen.generate_rust

fmt:
    cd balloons-rs
    cargo +nightly fmt --all

clippy:
    cd balloons-rs
    cargo clippy --workspace --all-targets --all-features

test-core:
    {{py}} pytest -q tests

test-plugins:
    {{py}} pytest -q plugins

build: gen
    maturin develop --release --manifest-path balloons-rs/crates/balloons-py/Cargo.toml
