# FranklinWH Direct Connect Bridge

An **unofficial** local REST + MQTT bridge and web UI for the FranklinWH aGate, using the
gateway's Direct Connect local API. It runs as a **Home Assistant add-on**, in **Docker**, or
standalone.

<!-- The five paragraphs below are the in-app disclaimer, VERBATIM: the "lines" of
     GET /api/disclaimer, in api_disclaimer() in src/franklinwh_direct_connect_bridge/app.py.
     Change the wording there, then here. tests/test_docs_disclaimer.py fails if this page
     stops containing each line exactly. Keep each paragraph on one line. -->

!!! warning "Unofficial software"

    This is an UNOFFICIAL app - NOT affiliated with, or endorsed by, FranklinWH.

    It talks to FranklinWH's undocumented Direct Connect (local) API and its cloud API - technically the SAME private API the official FranklinWH mobile app (and the FleetView installer portal) use, intended for those apps and not for third parties - plus the standard SunSpec Modbus TCP API (with undocumented FranklinWH extensions). Any of these may change, break, or become unavailable without notice.

    Provided AS-IS, without warranty of any kind. Use entirely at your own risk - the authors accept no liability for data loss, equipment damage, or service loss.

    Do NOT contact FranklinWH support about this app. Raise issues, defects, or feature requests on GitHub instead.

    Keep your system compliant with the settings your official FranklinWH app / installer configured. Using this tool to bypass safety, grid-compliance, or programme restrictions is at your own risk and is not condoned. Provided AS-IS for education/information; any use (personal or commercial) is permitted under the MIT Licence and entirely at your own risk. Please keep this notice with copies and forks (see Full terms).

    [Documentation](guide/index.md) · [GitHub Issues](https://github.com/david2069/franklinwh-direct-connect-bridge/issues) · [Full terms](#full-terms)

## Questions, ideas and help: GitHub Discussions

**[Join the conversation on GitHub Discussions](https://github.com/david2069/franklinwh-direct-connect-bridge/discussions)**. Everyone is welcome, technical or
not; you don't need to know any code. Ask or talk about anything to do with the bridge or
FranklinWH home batteries:

- installing it, or getting it running in Home Assistant or Docker;
- something not working, or looking wrong;
- an idea or a feature you'd like;
- the documentation: what's unclear or missing;
- your own setup, and related topics.

Not sure whether it's a defect? Start a discussion. It can be turned into an issue later.
If you already know it's a defect, you can also raise it in
[GitHub Issues](https://github.com/david2069/franklinwh-direct-connect-bridge/issues).

## Full terms

The bridge's licence: the MIT License and its Additional Terms. This is the repository's
[LICENSE](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/LICENSE)
file, included here as it stands, and the page the in-app **Full terms** link opens.

<!-- Included from LICENSE at build time (pymdownx.snippets), so it cannot drift. -->
```text
--8<-- "LICENSE"
```

## Start here

- **[User guide](guide/index.md):** the web UI, the scheduler, Home Assistant and MQTT,
  controls, energy and costs, several gateways.
- **[Developers Guide](developers/index.md):** the REST API and OpenAPI schema, how the web
  UI uses it, the MQTT topics, reading Home Assistant, and an end-to-end Scheduler example.
- **Installing:** see
  [INSTALL.md](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/INSTALL.md)
  and the add-on's
  [DOCS.md](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/DOCS.md).
- **What changed:** the
  [CHANGELOG](https://github.com/david2069/franklinwh-direct-connect-bridge/blob/main/CHANGELOG.md).

## How it is built and released

- **[Test and release policy](TEST_POLICY.md):** the gates every release passes.
- **[Feature parity](PARITY_GAP.md)** with the FranklinWH Modbus Bridge and FWHAI.

## Related FranklinWH projects

Libraries and tools from the same author. Each is unofficial, like this bridge.

| Project | What it is | Docs | Package |
|---|---|---|---|
| [franklinwh-direct-connect-api](https://github.com/david2069/franklinwh-direct-connect-api) | The Direct Connect (local) API library and CLI this bridge is built on | [site](https://david2069.github.io/franklinwh-direct-connect-api/) | [PyPI](https://pypi.org/project/franklinwh-direct-connect-api/) |
| [franklinwh-cloud](https://github.com/david2069/franklinwh-cloud) | The FranklinWH cloud API library, used by the bridge's cloud features | [site](https://david2069.github.io/franklinwh-cloud/) | [PyPI](https://pypi.org/project/franklinwh-cloud/) |
| [franklinwh-modbus](https://github.com/david2069/franklinwh-modbus) | The Modbus TCP (SunSpec) library and battery control, used by the bridge's Modbus client | [site](https://david2069.github.io/franklinwh-modbus/) | [PyPI](https://pypi.org/project/franklinwh-modbus/) |
| [franklinwh-modbus-bridge](https://github.com/david2069/franklinwh-modbus-bridge) | A separate bridge that reads the aGate over Modbus TCP and publishes it, with its own [Discussions](https://github.com/david2069/franklinwh-modbus-bridge/discussions) | [site](https://david2069.github.io/franklinwh-modbus-bridge/) | n/a |
| [franklinwh-gateway-emulator](https://github.com/david2069/franklinwh-gateway-emulator) | An aGate emulator for testing without hardware | [repo](https://github.com/david2069/franklinwh-gateway-emulator) | n/a |
