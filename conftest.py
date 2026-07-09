# Намеренно пустой. Наличие conftest.py в корне заставляет pytest добавить
# корень проекта в sys.path — иначе тесты из tests/ не найдут модули
# (chunker, config и т.д.) и упадут с ModuleNotFoundError.
