# Session Error Test

Test that errors in session blocks are caught and reported correctly.

## Syntax error

```python session=main
x = 1
print(x)
```

<!--Result:-->
```
1
```

```python session=main
# This should cause a NameError
print(undefined_variable)
```

<!--Error:-->
```
Traceback (most recent call last):
  File "/home/lesh/coding/md-babel-python/md_babel_py/session_server.py", line 56, in main
    result = eval(compile(code, "<block>", "eval"), namespace)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<block>", line 2, in <module>
NameError: name 'undefined_variable' is not defined

```

## After error - session should still work

```python session=main
print("session still alive")
```

<!--Result:-->
```
session still alive
```
