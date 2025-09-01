import importlib.util
spec = importlib.util.spec_from_file_location('app','app.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print('OK routes', len(m.app.url_map._rules))
