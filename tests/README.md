Run the regression suite with Python 3.11:

```sh
python -m pip install -r tests/requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin -o asyncio_default_fixture_loop_scope=function tests -q
```

Tests use temporary Red Config storage and mocked Discord and HTTP services. They do not connect a bot or modify live server data.
