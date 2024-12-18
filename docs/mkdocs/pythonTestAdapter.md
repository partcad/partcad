# `pythonTestAdapter`

```text
Traceback (most recent call last):
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/parser.py", line 266, in parse_source
    self._ast_root = ast.parse(self.text)
  File "/usr/local/lib/python3.10/ast.py", line 50, in parse
    return compile(source, filename, mode, flags,
  File "<unknown>", line 1
    {% set defined_variable = "defined" %}
     ^
SyntaxError: invalid syntax

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/vscode/.vscode-server/extensions/ms-python.python-2024.22.0-linux-x64/python_files/vscode_pytest/run_pytest_script.py", line 64, in <module>
    pytest.main(arg_array)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/config/__init__.py", line 175, in main
    ret: ExitCode | int = config.hook.pytest_cmdline_main(config=config)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_hooks.py", line 513, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
    raise exception.with_traceback(exception.__traceback__)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 103, in _multicall
    res = hook_impl.function(*args)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/main.py", line 330, in pytest_cmdline_main
    return wrap_session(config, _main)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/main.py", line 318, in wrap_session
    config.hook.pytest_sessionfinish(
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_hooks.py", line 513, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
    raise exception.with_traceback(exception.__traceback__)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 122, in _multicall
    teardown.throw(exception)  # type: ignore[union-attr]
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/logging.py", line 868, in pytest_sessionfinish
    return (yield)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 122, in _multicall
    teardown.throw(exception)  # type: ignore[union-attr]
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/terminal.py", line 893, in pytest_sessionfinish
    result = yield
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 122, in _multicall
    teardown.throw(exception)  # type: ignore[union-attr]
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/warnings.py", line 141, in pytest_sessionfinish
    return (yield)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 103, in _multicall
    res = hook_impl.function(*args)
  File "/home/vscode/.vscode-server/extensions/ms-python.python-2024.22.0-linux-x64/python_files/vscode_pytest/__init__.py", line 464, in pytest_sessionfinish
    analysis = cov.analysis2(file)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/control.py", line 929, in analysis2
    analysis = self._analyze(morf)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/control.py", line 946, in _analyze
    return analysis_from_file_reporter(data, self.config.precision, file_reporter, filename)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/results.py", line 31, in analysis_from_file_reporter
    statements = file_reporter.lines()
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/python.py", line 195, in lines
    return self.parser.statements
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/python.py", line 190, in parser
    self._parser.parse_source()
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/parser.py", line 273, in parse_source
    raise NotPython(
coverage.exceptions.NotPython: Couldn't parse '/workspaces/partcad/partcad/tests/unit/data/subdir/include.j2' as Python source: 'invalid syntax' at line 1

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/parser.py", line 266, in parse_source
    self._ast_root = ast.parse(self.text)
  File "/usr/local/lib/python3.10/ast.py", line 50, in parse
    return compile(source, filename, mode, flags,
  File "<unknown>", line 1
    {% set defined_variable = "defined" %}
     ^
SyntaxError: invalid syntax

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/home/vscode/.vscode-server/extensions/ms-python.python-2024.22.0-linux-x64/python_files/vscode_pytest/run_pytest_script.py", line 67, in <module>
    run_pytest(args)
  File "/home/vscode/.vscode-server/extensions/ms-python.python-2024.22.0-linux-x64/python_files/vscode_pytest/run_pytest_script.py", line 23, in run_pytest
    pytest.main(arg_array)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/config/__init__.py", line 175, in main
    ret: ExitCode | int = config.hook.pytest_cmdline_main(config=config)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_hooks.py", line 513, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
    raise exception.with_traceback(exception.__traceback__)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 103, in _multicall
    res = hook_impl.function(*args)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/main.py", line 330, in pytest_cmdline_main
    return wrap_session(config, _main)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/main.py", line 318, in wrap_session
    config.hook.pytest_sessionfinish(
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_hooks.py", line 513, in __call__
    return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_manager.py", line 120, in _hookexec
    return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
    raise exception.with_traceback(exception.__traceback__)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 122, in _multicall
    teardown.throw(exception)  # type: ignore[union-attr]
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/logging.py", line 868, in pytest_sessionfinish
    return (yield)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 122, in _multicall
    teardown.throw(exception)  # type: ignore[union-attr]
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/terminal.py", line 893, in pytest_sessionfinish
    result = yield
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 122, in _multicall
    teardown.throw(exception)  # type: ignore[union-attr]
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/_pytest/warnings.py", line 141, in pytest_sessionfinish
    return (yield)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/pluggy/_callers.py", line 103, in _multicall
    res = hook_impl.function(*args)
  File "/home/vscode/.vscode-server/extensions/ms-python.python-2024.22.0-linux-x64/python_files/vscode_pytest/__init__.py", line 464, in pytest_sessionfinish
    analysis = cov.analysis2(file)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/control.py", line 929, in analysis2
    analysis = self._analyze(morf)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/control.py", line 946, in _analyze
    return analysis_from_file_reporter(data, self.config.precision, file_reporter, filename)
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/results.py", line 31, in analysis_from_file_reporter
    statements = file_reporter.lines()
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/python.py", line 195, in lines
    return self.parser.statements
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/python.py", line 190, in parser
    self._parser.parse_source()
  File "/workspaces/partcad/.venv/lib/python3.10/site-packages/coverage/parser.py", line 273, in parse_source
    raise NotPython(
coverage.exceptions.NotPython: Couldn't parse '/workspaces/partcad/partcad/tests/unit/data/subdir/include.j2' as Python source: 'invalid syntax' at line 1
```

Starting now, all test run output will be sent to the Test Result panel, while test discovery output will be sent to the
"Python" output channel instead of the "Python Test Log" channel. The "Python Test Log" channel will be deprecated
within the next month. See [New Method for Output Handling in Python Testing] for details.

[New Method for Output Handling in Python Testing]:
  https://github.com/microsoft/vscode-python/wiki/New-Method-for-Output-Handling-in-Python-Testing
