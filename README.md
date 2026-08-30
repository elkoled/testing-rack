# testing-rack

Reserve and access devices on a shared test rack.

Requires Python 3.12 and `uv`.
Set each `serial` in `config.json` to its 8-character comma serial.

```sh
python3 app.py init
python3 app.py serve
```

Open <http://localhost:8765>. Run the complete lifecycle suite with:

```sh
./tests.sh
```

Production examples are in `deploy/`. Test details are in `TESTING.md`.
