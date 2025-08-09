# ADBImgDetection — Developer Docs

This documentation targets programmers and focuses on the API and CLI for building reliable image-driven automations.

Contents
- Overview: concepts, architecture — see docs/Overview.md
- API Reference (Python) — see docs/API.md
- CLI Reference (Commands) — see docs/CLI.md
- Workflows and Scripting Patterns — see docs/Workflows.md
- Templates and Matching Tips — see docs/Templates.md
- OCR Utilities — see docs/OCR.md

Workspace
- Core: [bot.py](../bot.py) — class [`bot.Bot`](../bot.py)
- CLI: [cli.py](../cli.py), entrypoint [main.py](../main.py)
- Examples: [examples/my_flow.py](../examples/my_flow.py), [examples/advanced_flow.py](../examples/advanced_flow.py), docs: [examples/workflow.md](../examples/workflow.md)

Conventions
- Image templates live under img/. Pass bare names like "mainmenumyfarm.png"; [`bot.Bot`](../bot.py) auto-prefixes img/.
- Coordinates are device pixels.
- All template methods use OpenCV template matching with threshold in [0, 1].