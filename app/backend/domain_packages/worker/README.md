<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Isolated package workers

Build the trusted runtime from the Lunar root:

```sh
python scripts/build_worker_image.py --tag lunar-worker:local
```

The build copies only the root dependency declarations, the planner dependency
metadata, and the image-owned worker/Prism engine. It installs the locked generic
`mcp-backend` group. No domain package is installed in the API or base image.
`prepare_runtime` explicitly installs one imported version's hash-pinned binary
wheels in a derived image and records its immutable Docker ID. Preparation is
serialized by a PostgreSQL advisory lock. Import and planning never prepare a
runtime implicitly. `recover_runtime_preparations` fails abandoned work while
respecting active preparation locks.

`load_runtime` requires an owned ready import and a prepared runtime. Workers
receive four read-only collection mounts and one writable run directory. Their
root filesystem is read-only; network, Linux capabilities, privilege escalation,
Docker sockets, API environment and PostgreSQL access are unavailable.

The JSON request/result schemas are in `../format/`. Registered Python hooks
run only inside this container:

- `prepare(workflow_id, inputs, run_id, run_root, network_authority,
  on_reasoning, public_fetch=None)` returns `prepared_input`, optional private
  `state`, and optional `{kind, payload}` events. `state` never leaves the worker.
  `public_fetch` is supplied only when network authority is granted.
- `plan(request)` returns JSON policy data. The request has `operation` and
  `input`. Policy calls have no network/model authority. Batches invoke the same
  registered hook independently for each request; they cannot select other hooks.
- `verify(state, execution, services)` returns a contract-shaped `result` and
  optional events. `execution` is the actual typed Prism result. `services`
  exposes the public model snapshot, authorized completion callback, and event
  callback. This verification follows execution in the same worker; independent
  replay verification is unavailable without a package replay contract.

`on_reasoning(**payload)` emits observed reasoning events. Returned events,
artifact inventories, byte sizes/digests, workflow schemas and report verification
are validated by the host. Non-JSON values fail explicitly. A workflow declaring
a verification hook must return a passing report verification receipt.

Provider calls use one already-owned model connection. Package overrides cannot
change its provider, endpoint, key, headers or tools. Credentials remain on the
host. Calls and pipe writes honor the worker's cancellation/deadline; a provider
request already in progress retains its own bounded timeout.

Public download calls use `public_fetch('open', url=...)`, then
`public_fetch('read', token=..., size=...)` and `public_fetch('close', token=...)`.
The host permits only URLs declared in this version's source documents, public
HTTPS on port 443, and same-host HTTPS redirects. It validates DNS answers and
pins the checked address to the TLS connection. One stream is open at a time,
reads are at most 1 MiB, and cumulative downloaded bytes are bounded. Returned
read data is base64. The worker remains disconnected from the network.

`runs.enqueue` holds a run lease on its accepting database connection. Keep this
connection open through `execute_queued`, then close it to release the lease.
Each event is committed before execution continues. Only validated successful
results create outputs; output, artifact receipts and completion commit together.
Recovery skips live leases and never queues imported historical runs.

Default limits: 2 GiB container memory, 2 CPUs, 256 processes, 30-minute execution,
32 MiB worker output, 8 GiB artifacts, and 2 GiB public downloads. Read-only
planning uses a 2-minute deadline and permits a 128 MiB request because complete
imported skill contracts can exceed the ordinary 32 MiB request bound. Responses
retain the ordinary bound. Policy caches belong to one planner invocation and
one selected runtime; nothing is shared across owners or versions.
