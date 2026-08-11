# Mini Ledger (legacy Flask demo)

A small invoice management service built with Flask blueprints. This repository
exists as a migration target for the Autonomous Code Migration Agent
(Flask -> FastAPI).

## Layout

```
app/
├── routes/      # HTTP endpoints (blueprints)
├── services/    # business logic + in-memory storage
├── models/      # dataclass models with validation
└── utils/       # shared validation helpers
tests/           # pytest suite (framework-agnostic assertions)
run.py           # entry point
```

## Run

```
pip install -r requirements.txt
python run.py
```

## Test

```
pytest
```
