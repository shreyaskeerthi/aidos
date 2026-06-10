# SiteOps Validator MVP

Standalone MVP to validate infrastructure deployments using:

- Planned state (`BOM`)
- Site constraints (`site survey`)
- Real state (`command outputs`)

This is intentionally independent from the GroundTruth app.

## What it does

- Parses site survey and BOM files (JSON, CSV, XLSX)
- Normalizes common deployment fields
- Runs a deterministic validation rule engine
- Produces a structured validation report (critical, warning, passed)
- Optionally runs shell commands and evaluates pass/fail patterns

## Quick start

```powershell
cd siteops_validator
py -3 -m pip install -r requirements.txt
```

### 1) Parse and normalize survey

```powershell
py -3 -m siteops.cli parse-survey --survey "examples/site_survey_example.json" --out "artifacts/survey_normalized.json"
```

### 2) Validate BOM + survey

```powershell
py -3 -m siteops.cli validate --survey "examples/site_survey_example.json" --bom "examples/bom_example.json" --out "artifacts/validation_report.json"
```

### 3) Run command checks

```powershell
py -3 -m siteops.cli run-checks --checks "examples/command_checks.json" --out "artifacts/command_report.json"
```

### 4) Full run

```powershell
py -3 -m siteops.cli full-run --survey "examples/site_survey_example.json" --bom "examples/bom_example.json" --checks "examples/command_checks.json" --out "artifacts/full_report.json"
```

## Input model

### Site survey (example)

```json
{
  "loading_dock": "yes",
  "server_lift": "no",
  "rack_floor_psf": 150,
  "liquid_cooling": "no",
  "power": "208V 30A 3-phase",
  "available_circuits": "yes",
  "uplinks": "2x10G",
  "ports_40g": "yes",
  "vlan_config_needed": "yes",
  "network_diagram_provided": "no",
  "layout_blueprint_provided": "no"
}
```

### BOM (example)

```json
{
  "gpu_model": "H100",
  "node_count": 8,
  "target_platform": "Cisco AI Pod"
}
```

## Rule engine behavior

Built-in high-value rules include:

- Missing server lift for heavy installs => critical
- Air-only cooling with H100 => warning
- Missing network diagram => warning
- Missing layout blueprint => warning
- Missing VLAN plan when VLAN config is needed => critical
- Positive checks for dock/circuits/rack load/power/uplink availability

## Notes

- XLSX parsing requires `pandas` + `openpyxl`.
- Command checks are shell commands; execute only trusted configs.
