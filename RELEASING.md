# Releasing legacylens

## Versioning
- Semantic versioning. Bump `version` in both `pyproject.toml` and
  `src/legacylens/__init__.py`, and add a `CHANGELOG.md` entry.

## Build distributions
```bash
python -m pip install --upgrade build twine
python -m build            # -> dist/legacylens-<v>.tar.gz and .whl
python -m twine check dist/*
```

## Offline bundle (air-gapped installs)
```bash
bash scripts/build_offline_bundle.sh          # Windows: scripts\build_offline_bundle.ps1
# -> dist/wheelhouse/ with the legacylens wheel + all dependency wheels
```
On the air-gapped host (no network):
```bash
pip install --no-index --find-links wheelhouse legacylens
pip install --no-index --find-links wheelhouse "legacylens[antlr]"   # with ANTLR runtime
```

## Tag
```bash
git tag -a v0.1.0 -m "legacylens 0.1.0"
git push origin v0.1.0
```

## Publish to PyPI (optional)
```bash
python -m twine upload dist/legacylens-<v>.tar.gz dist/legacylens-<v>-py3-none-any.whl
```
Then `pip install legacylens` / `pipx install legacylens` work anywhere.

## Sanity check before tagging
```bash
pytest                      # full suite green
legacylens doctor           # environment/deps OK
```
