// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import ReactMarkdown from "react-markdown";
import { useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";

import { BackButton } from "@/components/back-button";
import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { SkillBindings } from "@/components/skills/skill-bindings";
import { humanizeSkillPart } from "@/lib/skills";
import { useSkill } from "@/lib/use-skills";

export function SkillDetailPage() {
  const { id } = useParams();
  const { skill, error } = useSkill(id);

  if (error?.status === 404) return <EmptyState title="Skill not found" description="This canonical skill does not exist." />;
  if (error) return <PageError error={error} />;
  if (!skill) return <LoadingState label="Loading skill…" />;

  const path = [skill.role, skill.theme, skill.cluster].filter(Boolean).map(humanizeSkillPart);
  return (
    <section className="skill-detail-page">
      <BackButton to="/skills" />
      <PageHeader title={skill.display_name} />
      <nav className="skill-hierarchy-path" aria-label="Skill hierarchy">
        {path.map((part, index) => <span key={part}>{part}{index < path.length - 1 && <b aria-hidden="true">/</b>}</span>)}
      </nav>
      <div className="skill-detail-grid">
        <Card className="skill-overview">
          <p>{skill.description}</p>
          <dl>
            <div><dt>Identifier</dt><dd><code>{skill.skill_id}</code></dd></div>
            <div><dt>Version</dt><dd><code>{skill.version}</code></dd></div>
            {[["Role", skill.role], ["Theme", skill.theme], ["Cluster", skill.cluster]].filter(([, value]) => value).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{humanizeSkillPart(value)}</dd></div>)}
            {!!skill.groups?.length && <div><dt>Groups</dt><dd>{skill.groups.join(", ")}</dd></div>}
            <div><dt>Source</dt><dd><code>{skill.source_path}</code></dd></div>
          </dl>
        </Card>
        <Card className="skill-instructions">
          <ul>{(skill.files || []).map((file) => <li key={file.id}><a href={file.url}>{file.path}</a></li>)}</ul>
          <p className="eyebrow">Instructions</p>
          <ReactMarkdown components={{ h1: (props) => <h2 {...props} /> }} remarkPlugins={[remarkGfm]}>{skill.instructions}</ReactMarkdown>
        </Card>
      </div>
      <SkillBindings invocation={skill.invocation} />
    </section>
  );
}
