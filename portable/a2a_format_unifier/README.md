# A2A Format Unifier source

Shared format conversion with an Agent Zero adapter. Hermes remains unchanged.
The installable distribution is [`../../plugins/a2a_format_unifier`](../../plugins/a2a_format_unifier/).
Only Agent Zero is currently integrated and runtime-verified; additional
frameworks can bind the core without duplicating its wire-format decisions.

## Ownership

- `core/formats.py`: non-mutating normalization and encoding for known wire profiles.
- `core/client.py`: bounded standard-library JSON-RPC client and persistent context.
- `core/middleware.py`: ASGI legacy-server request/response conversion, no host imports.
- `adapters/agent_zero/`: native tool, config, prompts, guarded startup binding, docs.
- `tests/`: regression fixtures and fake transport/ASGI tests.
- `build.py`: deterministic assembly; includes core in `helpers/` and repository license.

The core has no Agent Zero or Hermes imports. The ASGI interface is a transport
boundary, not a dependency on an ASGI framework package. Authentication remains
owned by the configured client credential and the wrapped native server.

## Assemble and verify

Run from the repository root with Python 3.10 or newer:

```sh
python portable/a2a_format_unifier/build.py --check
# For a fresh distribution, the output directory must be empty:
python portable/a2a_format_unifier/build.py --output /tmp/a2a-dist/a2a_format_unifier
cd /tmp
PYTHONPATH=/tmp/a2a-dist python -m unittest discover -s /absolute/path/to/checkout/portable/a2a_format_unifier/tests -v
```

On Windows set `PYTHONPATH` in the current shell before running the same unittest
command. The tests import the assembled package, not a sibling source tree.
Assembly never removes existing files; create a new output directory when
updating the distribution, review its diff, then refresh the tracked package.

Keep private credentials, installed `config.json`, toggle files, `.runtime/`,
and bytecode out of both source and distribution. No standalone distribution
repository is configured. Publish changes through a draft monorepo PR.

See the [installation guide](adapters/agent_zero/README.md) and
[verification evidence](VERIFICATION.md). The supported legacy 0.2.5 profile is
the observed FastA2A schema; this is not blanket support for all A2A 0.2 systems.
