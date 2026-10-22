// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { BookOpen, ChevronRight, Search } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Searchbar } from "@/components/ui/searchbar";
import { skillCountLabel } from "@/lib/skills";
import { useSkills } from "@/lib/use-skills";

function BranchTrigger({ label, count }) {
  return (
    <CollapsibleTrigger className="skill-branch-trigger">
      <ChevronRight className="skill-disclosure-chevron" aria-hidden="true" />
      <span>{label}</span>
      <small>{skillCountLabel(count)}</small>
    </CollapsibleTrigger>
  );
}

function SkillLeaf({ skill, level }) {
  return (
    <div className="skill-leaf-item" role="treeitem" aria-level={level}>
      <Link className="skill-leaf" to={`/skills/${encodeURIComponent(skill.skill_id)}`}>
        <span className="asset-icon"><BookOpen aria-hidden="true" /></span>
        <span className="skill-row-copy">
          <strong>{skill.display_name}</strong>
          <small>{skill.description}</small>
          <code>{skill.skill_id}</code>
        </span>
        <ChevronRight className="row-chevron" aria-hidden="true" />
      </Link>
    </div>
  );
}

function SkillBranch({ branch, reveal, level = 1 }) {
  const ungrouped = branch.id === "ungrouped";
  const childLevel = ungrouped ? level : level + 1;
  const groups = branch.themes ?? branch.clusters;
  const children = groups
    ? groups.map((group) => (
      <SkillBranch key={group.id} branch={group} reveal={reveal} level={childLevel} />
    ))
    : branch.skills.map((skill) => (
      <SkillLeaf key={skill.skill_id} skill={skill} level={childLevel} />
    ));

  if (ungrouped) return children;

  const branchClass = ["skill-role", "skill-theme", "skill-cluster"][level - 1];
  return (
    <Collapsible className={`skill-branch ${branchClass}`} defaultOpen={reveal} role="treeitem" aria-level={level}>
      <BranchTrigger label={branch.label} count={branch.count} />
      <CollapsibleContent className="skill-branch-content" role="group">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function SkillsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const { hierarchy, error } = useSkills(query);

  function search(event) {
    const next = new URLSearchParams(searchParams);
    const value = event.target.value;
    if (value) next.set("q", value);
    else next.delete("q");
    next.delete("page");
    setSearchParams(next, { replace: true });
  }

  if (error) return <PageError error={error} />;
  if (!hierarchy) return <LoadingState label="Loading skills…" />;

  const reveal = Boolean(query.trim());
  return (
    <>
      <PageHeader title="Skills" />
      <div className="skills-toolbar">
        <Searchbar className="skills-search" label="Search skills" value={query} onChange={search} placeholder="Search skills…" />
        <span>{skillCountLabel(hierarchy.total)}</span>
      </div>
      {hierarchy.total ? (
        <section className="skills-tree" role="tree" aria-label="Canonical skills">
          {hierarchy.roles.map((role) => (
            <SkillBranch key={`${role.id}:${reveal}`} branch={role} reveal={reveal} />
          ))}
        </section>
      ) : <EmptyState icon={Search} title="No matching skills" description="Try a different identifier, description, role, theme, or cluster." />}
    </>
  );
}
