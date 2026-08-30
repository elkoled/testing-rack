# testing-rack

Small reservation server and restricted SSH gateway for a shared hardware test
rack. Configure devices in `config.json`; no rack hardware is touched by tests.

```sh
python3 testing_rack.py init
python3 testing_rack.py serve
```

Open <http://127.0.0.1:8765>. Run the complete lifecycle suite with:

```sh
./tests.sh
```

Production systemd and restricted-SSH examples are in `deploy/`.
