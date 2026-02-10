# Durus Performance Benchmarks

Comprehensive performance benchmark suite for the Durus object database.

## Installation

```bash
pip install -e ".[dev]"
```

## Running Benchmarks

```bash
# Run all benchmarks
pytest benchmarks/ --benchmark-only

# Generate HTML report
pytest benchmarks/ --benchmark-only --benchmark-autosave

# Compare against baseline
pytest benchmarks/ --benchmark-only --benchmark-compare
```

## Interpreting Results

### Key Metrics

1. **Serialization Speed**: Lower is better

   - msgspec should be 2-5x faster than pickle

1. **Serialized Size**: Smaller is better

   - msgspec typically 20-40% smaller than pickle

1. **Operation Latency**: Lower is better

   - Memory storage: \<1ms
   - File storage: 1-5ms
   - SQLite storage: 2-10ms
