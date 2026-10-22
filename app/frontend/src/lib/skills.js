// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { api } from "./api.js";

export function skillsListPath(query = "") {
  const params = new URLSearchParams();
  const normalized = query.trim();
  if (normalized) params.set("q", normalized);
  const suffix = params.toString();
  return suffix ? `/api/skills?${suffix}` : "/api/skills";
}

export function skillDetailPath(skillId) {
  return `/api/skills/${encodeURIComponent(skillId)}`;
}

export function humanizeSkillPart(value) {
  return String(value || "")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function skillCountLabel(count) {
  return `${count} ${count === 1 ? "skill" : "skills"}`;
}

function validString(value) {
  return typeof value === "string" && value.length > 0;
}

export function validateSkillHierarchy(payload) {
  if (!payload || !Number.isInteger(payload.total) || payload.total < 0 || !Array.isArray(payload.roles)) {
    throw new Error("The skill hierarchy has an unsupported format");
  }
  let total = 0;
  for (const role of payload.roles) {
    if (!validString(role.id) || !validString(role.label) || !Number.isInteger(role.count) || !Array.isArray(role.themes)) {
      throw new Error("The skill hierarchy has an unsupported format");
    }
    let roleCount = 0;
    for (const theme of role.themes) {
      if (!validString(theme.id) || !validString(theme.label) || !Number.isInteger(theme.count) || !Array.isArray(theme.clusters)) {
        throw new Error("The skill hierarchy has an unsupported format");
      }
      let themeCount = 0;
      for (const cluster of theme.clusters) {
        if (!validString(cluster.id) || !validString(cluster.label) || !Number.isInteger(cluster.count) || !Array.isArray(cluster.skills)) {
          throw new Error("The skill hierarchy has an unsupported format");
        }
        if (cluster.skills.some((skill) => !validString(skill.skill_id) || !validString(skill.display_name) || typeof skill.description !== "string")) {
          throw new Error("The skill hierarchy has an unsupported format");
        }
        if (cluster.count !== cluster.skills.length) {
          throw new Error("The skill hierarchy has inconsistent counts");
        }
        themeCount += cluster.count;
      }
      if (theme.count !== themeCount) throw new Error("The skill hierarchy has inconsistent counts");
      roleCount += theme.count;
    }
    if (role.count !== roleCount) throw new Error("The skill hierarchy has inconsistent counts");
    total += role.count;
  }
  if (payload.total !== total) throw new Error("The skill hierarchy has inconsistent counts");
  return payload;
}

export function validateSkillDetail(payload) {
  const fields = [
    "skill_id", "display_name", "version", "description", "instructions",
    "source_path",
  ];
  if (!payload || fields.some((field) => typeof payload[field] !== "string") || !validString(payload.skill_id)) {
    throw new Error("The skill detail has an unsupported format");
  }
  return payload;
}

export async function loadSkills(query = "") {
  return validateSkillHierarchy(await api(skillsListPath(query)));
}

export async function loadSkill(skillId) {
  return validateSkillDetail(await api(skillDetailPath(skillId)));
}
