# Integration Test

## Session support

```python session=main
x = 42
print(f"x is {x}")
```

<!--Result:-->
```
x is 42
```

```python session=main
y = x * 2
print(f"y is {y}")
```

<!--Result:-->
```
y is 84
```

## Expected error

```python expected-error
# This should fail - no session, x is not defined
print(f"x is {x}")
```

<!--Error:-->
```
Traceback (most recent call last):
  File "<stdin>", line 2, in <module>
NameError: name 'x' is not defined

Exit code: 1
```

## Skip

```python skip
# This block won't run
this_would_error()
```

## No-result (but still executes in session)

```python session=main no-result
# This runs but doesn't insert result
z = y + 10
```

```python session=main
# Should see z from previous block
print(f"z is {z}")
```

<!--Result:-->
```
z is 94
```

## Graphviz (raw mode)

```graphviz output=tests/output/graphviz-basic.svg
digraph {
  rankdir=LR
  A -> B -> C
}
```

<!--Result:-->
![output](tests/output/graphviz-basic.svg)

```graphviz output=tests/output/graphviz-args.svg args=-Grankdir=TB
digraph {
  A -> B -> C
  B -> D
}
```

<!--Result:-->
![output](tests/output/graphviz-args.svg)
