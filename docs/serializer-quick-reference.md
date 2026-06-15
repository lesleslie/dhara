# Serializer Quick Reference Guide

These serializers are exposed through `dhara.serialize`. `dhara` is the
canonical package name; the legacy `durus.*` import shim has been removed.

## Available Serializers

### 1. MsgspecSerializer (Recommended)

**Best for:** New databases, performance-critical applications

```python
from dhara.serialize import MsgspecSerializer

# MessagePack format (binary, fast, compact)
set = MsgspecSerializer(format="msgpack", use_builtins=True)

# JSON format (text, interoperable)
set = MsgspecSerializer(format="json", use_builtins=True)
```

**Performance:** 5-10x faster than pickle
**Security:** Safe (no code execution)
**Size:** 30-50% smaller than pickle

### 2. MsgpackSerializer (Msgpack wire format)

**Best for:** Existing code paths that want a named `msgpack` serializer

```python
from dhara.serialize import MsgpackSerializer

set = MsgpackSerializer()  # No arguments; msgspec-backed msgpack output
```

**Performance:** Same as `MsgspecSerializer(format="msgpack")`
**Security:** Safe (no code execution; msgspec-backed)
**Compatibility:** Output is msgpack, not the legacy Durus 4.x pickle stream

## Factory Function (Recommended)

```python
from dhara.serialize import create_serializer

# Create any serializer by name
set = create_serializer("msgspec", format="json")
set = create_serializer("msgpack")
```

## Basic Usage

```python
from dhara.serialize import create_serializer

# Create serializer
serializer = create_serializer("msgspec")

# Serialize
data = serializer.serialize({"key": "value"})

# Deserialize
result = serializer.deserialize(data)

# Extract state from Persistent object
state = serializer.get_state(persistent_obj)
```

## Choosing the Right Serializer

| Use Case | Recommended Serializer |
|----------|----------------------|
| New database | MsgspecSerializer |
| Performance critical | MsgspecSerializer |
| Need a named `msgpack` serializer | MsgpackSerializer |
| Interoperability needed | MsgspecSerializer (JSON format) |

## Security Guidelines

1. **Always use msgspec for new databases** - Safest option
1. **Use msgpack (msgspec-backed) when you need a named msgpack serializer** - Also safe
1. **Consider msgspec JSON format** - If you need text serialization
1. **Note**: The legacy `pickle` and `dill` serializers were removed in 0.11.0. The CWE-502 attack surface is closed.

## Performance Comparison

For a typical dictionary with 100 key-value pairs:

| Serializer | Time (relative) | Size (relative) |
|------------|----------------|----------------|
| Msgspec (MessagePack) | 0.1x | 0.5x |
| Msgspec (JSON) | 0.3x | 1.2x |
| MsgpackSerializer (msgspec-backed) | 0.1x | 0.5x |

## Migration Path

### From legacy Durus 4.x (pickle) to Dhara msgspec

```python
# Old Durus 4.x code
from dhara import Connection
connection = Connection("mydb.dhara")  # Uses pickle — no longer supported

# New Dhara code
from dhara import Connection
from dhara.serialize import MsgspecSerializer

serializer = MsgspecSerializer()
connection = Connection("mydb.dhara", serializer=serializer)
```

Note: Existing Durus 4.x pickle-format databases cannot be opened in 0.11.0
(opening one raises `ValueError`). Re-create the data in SHELF-1 format.

## Error Handling

```python
from dhara.serialize import create_serializer

# Handle invalid serializer name
try:
    set = create_serializer("invalid")
except ValueError as e:
    print(f"Unknown serializer: {e}")

# Handle invalid arguments
try:
    set = create_serializer("msgspec", invalid_arg=123)
except TypeError as e:
    print(f"Invalid arguments: {e}")
```

## Testing Your Serializers

```python
from dhara.serialize import create_serializer

# Test round-trip
serializer = create_serializer("msgspec")
test_data = {"key": "value", "list": [1, 2, 3]}

# Serialize
data = serializer.serialize(test_data)
print(f"Serialized size: {len(data)} bytes")

# Deserialize
result = serializer.deserialize(data)

# Verify
assert result == test_data
print("Round-trip successful!")
```

## Advanced Usage

### Custom Encoder for msgspec

```python
import msgspec
from dhara.serialize import MsgspecSerializer

# Create custom encoder for special types
encoder = msgspec.msgpack.Encoder()
serializer = MsgspecSerializer()
# Future: Support custom encoders
```

### Protocol Selection

```python
# No `protocol` argument is exposed — msgpack and msgspec handle framing internally
set = create_serializer("msgpack")
set = create_serializer("msgspec", format="json")
```

## Troubleshooting

### Problem: msgspec can't serialize my object

**Solution:** Implement `__getstate__` on the class to return a msgspec-compatible state dict

### Problem: Deserialization is slow

**Solution:** Use msgspec (already the default)

## Best Practices

1. **Use msgspec for all new databases**
1. **Test round-trip serialization for custom objects**
1. **Document which serializer your database uses**
1. **Never trust untrusted serialized data**

## Further Reading

- msgspec documentation
