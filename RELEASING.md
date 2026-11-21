# Releasing

This fork is distributed from its repository: users clone it and run it with `uv run --locked` (see the README), or build the Docker image. It is **not** published to PyPI: the `openosint` name there belongs to the upstream project, and this repository has no release workflow (the upstream Release and PyPI workflows were removed when the workflows were contained). A release is a version bump, a changelog entry, green CI on `main`, and a tag.

1. **Bump the version** (the docs-consistency test fails if these drift):
   - `pyproject.toml` (`[project] version`)
   - `.claude-plugin/plugin.json` (`version`); `tests/test_agent_skill.py` fails if it differs from `pyproject.toml`. (In this fork the skills run the local checkout and carry no PyPI pin, and there is no `.mcp.json`.)
   - `.mcp/server.json` (`version` and `packages[0].version`)
1a. **Rebuild the site**: `python scripts/build_site.py`. The docs pages show the version from `pyproject.toml`, so `scripts/check_site.py` (and CI) fails until you do. Refresh `stars` in `site/data/site.yaml` if you want the home page count current.
   - Changed `docs/favicon.svg`? Run `python scripts/render_favicons.py` (needs Pillow and Chrome) to regenerate the ICO and PNG icons.
2. **CHANGELOG.md**: rename `[Unreleased]` to `[X.Y.Z] — YYYY-MM-DD` and open a fresh `[Unreleased]`.
3. **Refresh the lock**: `uv lock`, commit it. CI runs `uv lock --check`, so a stale lock fails it.
4. **Check locally**: `pytest tests -q` and `ruff check openosint tests --extend-ignore I001`. Merge to `main` once CI is green.
5. **Tag**: `git tag vX.Y.Z && git push origin vX.Y.Z`. Nothing is published automatically: there is no release workflow in this fork.
6. **Check the tag**: in a fresh clone at the tag, `uv run --locked openosint web` starts with no `.env` and no keys, and `docker compose up --build` serves the web UI (the Install check runs the same on every pull request).
7. **Version numbers**: pick versions that cannot be mistaken for upstream releases. Upstream publishes `X.Y.Z` to PyPI; a fork version equal to an upstream one (as `2.38.2` is today) makes `openosint --version` ambiguous, so bump it before the first fork release.
