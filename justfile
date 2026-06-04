set shell := ["bash", "-cu"]

uv := "uv"
py := uv + " run --python " + venv_python
venv_python := ".venv/bin/python"
blue := '\033[1;34m'
green := '\033[1;32m'
yellow := '\033[1;33m'
reset := '\033[0m'

default:
    just --list

@banner color message:
    @printf '%b==> %s%b\n' "{{color}}" "{{message}}" "{{reset}}"

setup:
    @just banner {{quote(blue)}} 'setup: ensuring .venv and Python deps'
    {{uv}} venv --allow-existing .venv
    {{uv}} pip install --python {{venv_python}} -r requirements.txt maturin PyJWT pytest pytest-asyncio

gen: setup
    @just banner {{quote(blue)}} 'gen: regenerating Rust schema'
    {{py}} python -m codegen.generate_rust
    @just banner {{quote(blue)}} 'gen: regenerating typescript types'
    {{py}} python -m codegen.generate_typescript

fmt:
    cd balloons-rs
    cargo +nightly fmt --all

clippy:
    cd balloons-rs
    cargo clippy --workspace --all-targets --all-features

test-core: setup
    @just banner {{quote(green)}} 'test-core: running core pytest suite'
    {{py}} pytest -q tests

test-plugins: setup
    @just banner {{quote(green)}} 'test-plugins: running plugin pytest suite'
    {{py}} pytest -q plugins

test-scope scope: setup
    @just banner {{quote(green)}} 'test-scope: ensuring pytest is available'
    @if ! {{uv}} run python -c 'import pytest' >/dev/null 2>&1; then \
        {{uv}} pip install --python {{venv_python}} pytest pytest-asyncio; \
    elif ! {{uv}} run python -c 'import pytest_asyncio' >/dev/null 2>&1; then \
        {{uv}} pip install --python {{venv_python}} pytest-asyncio; \
    fi
    @just banner {{quote(green)}} 'test-scope: running pytest for {{scope}}'
    {{py}} python -m pytest -q {{scope}}

build: setup gen
    @just banner {{quote(yellow)}} 'build: developing balloons-py with maturin'
    {{uv}} run maturin develop --release --manifest-path balloons-rs/crates/balloons-py/Cargo.toml
    @just banner {{quote(yellow)}} 'build: developing ai-sdk-openai-compatible-py with maturin'
    {{uv}} run maturin develop --release --manifest-path balloons-rs/crates/ai-sdk-openai-compatible-py/Cargo.toml

test-ai-sdk: setup
    @just banner {{quote(green)}} 'test-ai-sdk: running ai-sdk Python bindings tests'
    cd balloons-rs/crates/ai-sdk-openai-compatible-py
    {{py}} pytest tests -v

test-ai-sdk-integration: setup
    @just banner {{quote(green)}} 'test-ai-sdk-integration: running Rust integration tests (requires server)'
    cd balloons-rs/crates/ai-sdk-openai-compatible-py
    {{py}} pytest tests/integration -v -s

test-ai-sdk-runner: setup build
    @just banner {{quote(green)}} 'test-ai-sdk-runner: running AISDKRunner tests'
    {{py}} pytest tests/test_ai_sdk_runner.py -v

test-ai-sdk-runner-integration: setup build
    @just banner {{quote(green)}} 'test-ai-sdk-runner-integration: running AISDKRunner integration tests (requires server)'
    {{py}} pytest tests/test_ai_sdk_runner_integration.py -v -s
