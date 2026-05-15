# Memory Address Output Test

This test outputs Python objects with memory addresses that change between runs.

```python
class Foo:
    pass

obj = Foo()
print(obj)
```

```results
<__main__.Foo object at 0x7f504c151340>
```

```python
# Multiple objects
class Bar:
    pass

objs = [Bar() for _ in range(3)]
for o in objs:
    print(o)
```

```results
<__main__.Bar object at 0x7fcbe8c4c860>
<__main__.Bar object at 0x7fcbe8c4c7d0>
<__main__.Bar object at 0x7fcbe8c4c8c0>
```

```python
# Lambda and function objects
fn = lambda x: x + 1
print(fn)

def bar():
    pass
print(bar)
```

```results
<function <lambda> at 0x7f3653af6660>
<function bar at 0x7f3653321120>
```

```python
# Mixed output with addresses
class Thing:
    pass

print("Regular text")
print(Thing())
print("More text")
print(f"Object: {Thing()}")
```

```results
Regular text
<__main__.Thing object at 0x7f62c2c4c830>
More text
Object: <__main__.Thing object at 0x7f62c2c4c830>
```
