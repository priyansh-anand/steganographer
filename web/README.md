# Browser demo

A static page that runs the real `steganographer` package entirely client-side via [Pyodide](https://pyodide.org):
`numpy`, `Pillow` and `cryptography` come from Pyodide's own package repo, `reedsolo` and this project's own
wheel are installed from PyPI/locally via micropip. Nothing the visitor picks is ever sent anywhere &mdash;
there is no server. Deployed to GitHub Pages by
[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) on every push to `master` that touches `src/`,
`web/` or `pyproject.toml`.

Four tabs: **Hide** (lsb/endian, password, and under Advanced: signing, a decoy for deniable hiding, adaptive
placement), **Reveal** (password, and under Advanced: requiring a specific signer), **Analyze** (the chi-square
and RS checks from `--analyze`), and **Keys** (generates an Ed25519 pair, the private key never leaves the
tab). It's the real package running, not a reimplementation of any of this in JavaScript.

## Developing locally

```sh
uv build -o web/dist          # from the repo root, builds the wheel app.js installs
cd web && python3 -m http.server 8000
```

Then open `http://localhost:8000`. `web/dist/` is gitignored, a fresh wheel every time avoids it silently going
stale against `src/`. If you bump `__version__` in `src/steganographer/__init__.py`, update the wheel filename
`app.js` installs to match &mdash; `micropip` needs a real [PEP 440](https://peps.python.org/pep-0440/) version
in the filename, so this can't be a symbolic name like `latest` (a real mistake made once while building this,
caught by testing the page rather than assuming the rename was safe).
