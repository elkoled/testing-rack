# testing-rack

Reserve devices on a shared test rack and access them through an SSH gateway.
The service provides a web UI, an HTTP API, and optional hardware controls.

## Quick start

Requires Python 3.12. The service has no third-party Python dependencies.

```sh
python3 app.py init
python3 app.py serve
```

Open <http://localhost:8765>. Initialization creates local state once and refuses
an overwrite. Local startup does not probe hardware: without `--health`, devices
are treated as ready. SSH commands use the gateway in `config.json`.

## Documentation

- [OpenAPI specification](web/openapi.json): reservation, SSH, expiry, and release workflow;
  also available through the website's **OpenAPI** link.
- [Deployment](docs/deployment.md): configuration, credentials, services, and updates.
- [Contributing](CONTRIBUTING.md): code layout and testing.
- [Device displays](device_display/README.md): optional AGNOS idle screen integration.
- [Rack assignment audit](docs/rack-assignment-audit.md): dated hardware observations.

## License

[MIT](LICENSE).
