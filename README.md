<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>

SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
Neuro-symbolic AI Group

SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
Neuro-symbolic AI Group

SPDX-License-Identifier: Apache-2.0
-->
# Lunar Platform

A workspace for PRISM repositories, skills, data sources, reports and workflows.

Lunar Platform brings every part of a PRISM project into one organized workspace,
from reusable skills and connected data sources to executable workflows and their
reports. It supports versioned package imports, making domain content portable and
straightforward to share, install, and maintain across environments. Clear package
boundaries keep projects isolated while allowing their resources to work together
as a coherent whole, without requiring a separate domain checkout.

See [loading external projects](docs/loading-external-projects.md),
[installation and operator guide](app/README.md),
[selection contracts](app/backend/domain_packages/SELECTION.md), and the
[internal planner module](planner/README.md). No domain checkout is required to install.
The installation guide also documents the package iteration CLI for uploading,
preparing, and executing a freshly exported package without using the web UI.

## License and release checks

Lunar Platform is licensed under [Apache-2.0](LICENSES/Apache-2.0.txt), with per-file REUSE
metadata and contributor attribution. See [third-party assets](THIRD_PARTY.md)
for separately licensed bundled software and [release preparation](RELEASE.md)
for installation, verification, and outstanding release prerequisites.
