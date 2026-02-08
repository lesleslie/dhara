# Serializer Quick Reference Guide

## Available Serializers

### 1. MsgspecSerializer (Recommended)
**Best for:** New databases, performance-critical applications

```python
from durus.serialize import MsgspecSerializer

# MessagePack format (binary, fast, compact)
ser = MsgspecSerializer(format="msgpack", use_builtins=True)

# JSON format (text, interoperable)
ser = MsgspecSerializer(format="json", use_builtins=True)
```

**Performance:** 5-10x faster than pickle
**Security:** Safe (no code execution)
**Size:** 30-50% smaller than pickle

### 2. PickleSerializer (Compatibility)
**Best for:** Backward compatibility with Durus 4.x

```python
from durus.serialize import PickleSerializer

ser = PickleSerializer(protocol=2)  # Durus 4.x default
ser = PickleSerializer(protocol=4)  # Better performance
```

**Performance:** Baseline
**Security:** Unsafe with untrusted data
**Compatibility:** 100% compatible with Durus 4.x

### 3. DillSerializer (Extended)
**Best for:** Serializing functions, lambdas, complex objects

```python
from durus.serialize import DillSerializer

try:
    ser = DillSerializer(protocol=4)
except ImportError:
    # Install dill first: pip install dill
    pass
```

**Performance:** Slower than pickle
**Security:** Unsafe with untrusted data
**Capability:** Can serialize functions/lambdas

## Factory Function (Recommended)

```python
from durus.serialize import create_serializer

# Create any serializer by name
ser = create_serializer("msgspec", format="json")
ser = create_serializer("pickle", protocol=4)
ser = create_serializer("dill", protocol=4)
```

## Basic Usage

```python
from durus.serialize import create_serializer

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
| Durus 4.x compatibility | PickleSerializer |
| Need to serialize functions | DillSerializer |
| Interoperability needed | MsgspecSerializer (JSON format) |

## Security Guidelines

1. **Always use msgspec for new databases** - Safest option
2. **Never deserialize untrusted data with pickle/dill** - Code execution risk
3. **Use pickle only for trusted data** - Backward compatibility only
4. **Consider msgspec JSON format** - If you need text serialization

## Performance Comparison

For a typical dictionary with 100 key-value pairs:

| Serializer | Time (relative) | Size (relative) |
|------------|----------------|----------------|
| Msgspec (MessagePack) | 0.1x | 0.5x |
| Msgspec (JSON) | 0.3x | 1.2x |
| Pickle | 1.0x | 1.0x |
| Dill | 1.5x | 1.3x |

## Migration Path

### From Durus 4.x (pickle) to Durus 5.0 (msgspec)

```python
# Old Durus 4.x code
from durus import Connection
connection = Connection("mydb.durus")  # Uses pickle

# New Durus 5.0 code (future)
from durus import Connection
from durus.serialize import MsgspecSerializer

# This will be supported in future updates
serializer = MsgspecSerializer()
connection = Connection("mydb.durus", serializer=serializer)
```

For now, use the factory to create serializers independently:

```python
from durus.serialize import create_serializer

# Create msgspec serializer for new data
serializer = create_serializer("msgspec")
data = serializer.serialize(new_object)

# Keep using pickle for existing Durus 4.x databases
pickle_serializer = create_serializer("pickle")
```

## Error Handling

```python
from durus.serialize import create_serializer

# Handle invalid serializer name
try:
    ser = create_serializer("invalid")
except ValueError as e:
    print(f"Unknown serializer: {e}")

# Handle missing dependencies
try:
    ser = create_serializer("dill")
except ImportError as e:
    print(f"Dependency missing: {e}")
    print("Install with: pip install dill")

# Handle invalid arguments
try:
    ser = create_serializer("pickle", invalid_arg=123)
except TypeError as e:
    print(f"Invalid arguments: {e}")
```

## Testing Your Serializers

```python
from durus.serialize import create_serializer

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
from durus.serialize import MsgspecSerializer

# Create custom encoder for special types
encoder = msgspec.msgpack.Encoder()
serializer = MsgspecSerializer()
# Future: Support custom encoders
```

### Protocol Selection for pickle/dill

```python
# Protocol 2: Python 2 compatible (Durus 4.x default)
ser = create_serializer("pickle", protocol=2)

# Protocol 4: Python 3.4+ (better performance)
ser = create_serializer("pickle", protocol=4)

# Protocol 5: Python 3.8+ (best performance)
ser = create_serializer("pickle", protocol=5)
```

## Troubleshooting

### Problem: ImportError with dill
**Solution:** Install dill: `pip install dill`

### Problem: msgspec can't serialize my object
**Solution:** Use pickle or dill instead, or implement `__getstate__`

### Problem: Deserialization is slow
**Solution:** Use msgspec instead of pickle

### Problem: Need to serialize a lambda
**Solution:** Use dill serializer

## Best Practices

1. **Use msgspec for all new databases**
2. **Specify protocol explicitly for pickle/dill**
3. **Test round-trip serialization for custom objects**
4. **Handle ImportError for optional dependencies**
5. **Document which serializer your database uses**
6. **Never trust untrusted serialized data**

## Further Reading

- [msgspec documentation](https://jcristharif.com/msgspec/)
- [Python pickle documentation](https://docs.python.org/3/library/pickle.html)
- [dill documentation](https://dill.readthedocs.io/)
