# testing-rack

Reserve and access devices on a shared test rack.

```sh
python3 app.py init
python3 app.py serve
```

Open <http://127.0.0.1:8765>. Run the complete lifecycle suite with:

```sh
./tests.sh
```

Production examples are in `deploy/`. Test details are in `TESTING.md`.
