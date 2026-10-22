// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  humanizeSkillPart,
  skillDetailPath,
  skillCountLabel,
  skillsListPath,
  validateSkillDetail,
  validateSkillHierarchy,
} from "./skills.js";

const hierarchy = {
  total: 1,
  roles: [{
    id: "readers",
    label: "Readers",
    count: 1,
    themes: [{
      id: "literature-and-evidence",
      label: "Literature And Evidence",
      count: 1,
      clusters: [{
        id: "source-and-evidence-acquisition",
        label: "Source And Evidence Acquisition",
        count: 1,
        skills: [{ skill_id: "example-skill", display_name: "Example Skill", description: "Example" }],
      }],
    }],
  }],
};

test("constructs list query and encoded detail API paths", () => {
  assert.equal(skillsListPath(), "/api/skills");
  assert.equal(skillsListPath("   "), "/api/skills");
  assert.equal(skillsListPath(" causal graph "), "/api/skills?q=causal+graph");
  assert.equal(skillDetailPath("skill/one"), "/api/skills/skill%2Fone");
});

test("presents deterministic human-readable hierarchy labels and counts", () => {
  assert.equal(humanizeSkillPart("source-and_evidence-acquisition"), "Source And Evidence Acquisition");
  assert.equal(skillCountLabel(1), "1 skill");
  assert.equal(skillCountLabel(12), "12 skills");
});

test("guards hierarchy shape and consistent branch counts", () => {
  assert.equal(validateSkillHierarchy(hierarchy), hierarchy);
  assert.throws(() => validateSkillHierarchy({ total: 1, roles: [] }), /inconsistent counts/);
  assert.throws(() => validateSkillHierarchy({ total: 0, roles: [{}] }), /unsupported format/);
});

test("guards canonical detail fields", () => {
  const detail = {
    ...hierarchy.roles[0].themes[0].clusters[0].skills[0],
    version: "1.0.0",
    instructions: "# Example",
    role: "readers",
    theme: "literature-and-evidence",
    cluster: "source-and-evidence-acquisition",
    source_path: "catalog/agents/readers/example/SKILL.md",
  };
  assert.equal(validateSkillDetail(detail), detail);
  assert.throws(() => validateSkillDetail({ ...detail, instructions: null }), /unsupported format/);
});

test("Skills pages use the API while Repository keeps the Prism catalog", () => {
  const skillsPage = readFileSync(new URL("../pages/skills-page.jsx", import.meta.url), "utf8");
  const detailPage = readFileSync(new URL("../pages/skill-detail-page.jsx", import.meta.url), "utf8");
  const repositoryPage = readFileSync(new URL("../pages/repository-page.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(skillsPage, /usePrismCatalog|prism-assets\/catalog\.json/);
  assert.doesNotMatch(detailPage, /usePrismCatalog|prism-assets\/catalog\.json/);
  assert.match(repositoryPage, /usePrismCatalog/);
});
