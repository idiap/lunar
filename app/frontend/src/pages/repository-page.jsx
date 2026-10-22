// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import {
  BookOpen,
  Boxes,
  ChevronRight,
  Download,
  FileCode2,
  LoaderCircle,
  Package,
  Plus,
  Trash2,
  Workflow,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState, LoadingState, PageError } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { usePackage } from "@/context/package-context";
import { api } from "@/lib/api";
import { usePrismCatalog } from "@/lib/use-prism-catalog";

function countLabel(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function Branch({ label, meta, level, defaultOpen = false, children }) {
  const branchClass = ["skill-role", "skill-theme", "skill-cluster"][level - 1] || "skill-cluster";
  return (
    <Collapsible className={`skill-branch ${branchClass}`} defaultOpen={defaultOpen} role="treeitem" aria-level={level}>
      <CollapsibleTrigger className="skill-branch-trigger">
        <ChevronRight className="skill-disclosure-chevron" aria-hidden="true" />
        <span>{label}</span>
        {meta && <small>{meta}</small>}
      </CollapsibleTrigger>
      <CollapsibleContent className="skill-branch-content" role="group">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

function Leaf({ icon: Icon, title, description, meta, href, to, level = 3 }) {
  const content = (
    <>
      <span className="asset-icon"><Icon aria-hidden="true" /></span>
      <span className="skill-row-copy">
        <strong>{title}</strong>
        {description && <small>{description}</small>}
        {meta && <code>{meta}</code>}
      </span>
      <ChevronRight className="row-chevron" aria-hidden="true" />
    </>
  );
  return (
    <div className="skill-leaf-item" role="treeitem" aria-level={level}>
      {to ? <Link className="skill-leaf" to={to}>{content}</Link> : <a className="skill-leaf" href={href}>{content}</a>}
    </div>
  );
}

function WorkflowLeaf({ module, versionId }) {
  const search = new URLSearchParams({ workflow: module.id, package_version_id: versionId });
  const details = [
    module.primary_file,
    Number.isInteger(module.file_count) ? countLabel(module.file_count, "file") : null,
    Number.isInteger(module.skill_count) ? countLabel(module.skill_count, "skill") : null,
  ].filter(Boolean).join(" · ");
  return (
    <Leaf
      icon={Workflow}
      title={module.name}
      description={module.description}
      meta={details}
      to={`/prism?${search}`}
    />
  );
}

function SkillLeaf({ skill, versionId }) {
  const search = new URLSearchParams({ package_version_id: versionId });
  return (
    <Leaf
      icon={BookOpen}
      title={skill.name}
      description={skill.description}
      meta={skill.id}
      to={`/skills/${encodeURIComponent(skill.id)}?${search}`}
    />
  );
}

function ResourceBranch({ resource }) {
  const files = resource.files || [];
  return (
    <Branch label={resource.name || resource.id} meta={countLabel(files.length, "file")} level={3}>
      {files.map((file) => (
        <Leaf
          key={file.id}
          icon={FileCode2}
          title={file.path}
          meta={file.media_type || countLabel(file.size, "byte")}
          href={file.url}
          level={4}
        />
      ))}
      {!files.length && <p className="repository-empty-branch">No linked files.</p>}
    </Branch>
  );
}

function PackageContents({ catalog, versionId }) {
  const modules = catalog.modules || [];
  const skills = catalog.skills || [];
  const resources = catalog.resources || [];
  const total = modules.length + skills.length + resources.length;

  if (!total) return <p className="repository-empty-branch">This package has no repository content.</p>;
  return (
    <>
      {!!modules.length && (
        <Branch label="Workflows" meta={countLabel(modules.length, "workflow")} level={2} defaultOpen>
          {modules.map((module) => <WorkflowLeaf key={module.id} module={module} versionId={versionId} />)}
        </Branch>
      )}
      {!!skills.length && (
        <Branch label="Skills" meta={countLabel(skills.length, "skill")} level={2} defaultOpen>
          {skills.map((skill) => <SkillLeaf key={skill.id} skill={skill} versionId={versionId} />)}
        </Branch>
      )}
      {!!resources.length && (
        <Branch label="Repository resources" meta={countLabel(resources.length, "resource")} level={2} defaultOpen>
          {resources.map((resource) => <ResourceBranch key={resource.resource_id || resource.id} resource={resource} />)}
        </Branch>
      )}
    </>
  );
}

function PackageBranch({ version, initiallyOpen, onDelete }) {
  const [open, setOpen] = useState(initiallyOpen);
  const [requestingDelete, setRequestingDelete] = useState(false);
  const deleting = requestingDelete || Boolean(version.deletion_started_at);
  const { catalog, error } = usePrismCatalog(version.id, open && !deleting);

  async function handleDelete() {
    setRequestingDelete(true);
    try {
      await onDelete(version);
    } finally {
      setRequestingDelete(false);
    }
  }

  return (
    <Collapsible className="skill-branch skill-role repository-package" open={open} onOpenChange={setOpen} role="treeitem" aria-level={1}>
      <div className="repository-package-row">
        <CollapsibleTrigger className="skill-branch-trigger">
          <ChevronRight className="skill-disclosure-chevron" aria-hidden="true" />
          <Package className="repository-package-icon" aria-hidden="true" />
          <span>{version.display_name}</span>
          <small>v{version.version}</small>
        </CollapsibleTrigger>
        {!deleting && (
          <a
            className={`${buttonVariants({ variant: "outline", size: "icon" })} repository-package-export`}
            href={`/api/packages/versions/${encodeURIComponent(version.id)}/export`}
            aria-label={`Export ${version.display_name} v${version.version} ZIP`}
            title="Export ZIP"
          >
            <Download aria-hidden="true" />
          </a>
        )}
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="danger repository-package-delete"
              disabled={deleting}
              title={deleting ? "Deleting package" : "Delete package"}
              aria-label={`${deleting ? "Deleting" : "Delete"} ${version.display_name} v${version.version}`}
            >
              {deleting ? <LoaderCircle className="spin" aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <p className="eyebrow">Delete package</p>
              <AlertDialogTitle>Delete “{version.display_name}” v{version.version}?</AlertDialogTitle>
              <AlertDialogDescription>
                Its repository files, skills, reports, runs, and saved chats will be permanently removed. This action cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction disabled={deleting} onClick={handleDelete}>Delete</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
      <CollapsibleContent className="skill-branch-content" role="group">
        {version.deletion_started_at ? <p className="repository-empty-branch">Deleting package…</p>
          : error ? <div className="repository-branch-feedback"><PageError error={error} /></div>
          : !catalog ? <LoadingState label={`Loading ${version.display_name}…`} />
            : <PackageContents catalog={catalog} versionId={version.id} />}
      </CollapsibleContent>
    </Collapsible>
  );
}

export function RepositoryPage() {
  const { versions, versionId, refresh, switchVersion } = usePackage();
  const input = useRef(null);
  const [importing, setImporting] = useState(false);
  const hasDeletingPackage = versions.some((version) => version.deletion_started_at);

  useEffect(() => {
    if (!hasDeletingPackage) return;
    const interval = window.setInterval(() => { refresh().catch(() => {}); }, 2000);
    return () => window.clearInterval(interval);
  }, [hasDeletingPackage]);

  async function removePackage(version) {
    try {
      await api(`/api/packages/versions/${encodeURIComponent(version.id)}`, { method: "DELETE" });
      await refresh();
      if (version.id === versionId) switchVersion(null);
      toast.info(`${version.display_name} v${version.version} is being deleted`);
    } catch (error) {
      toast.error(error.message);
    }
  }

  async function importPackage(event) {
    const file = event.target.files[0];
    if (!file) return;
    setImporting(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const result = await api("/api/packages/import", { method: "POST", body });
      await refresh();
      switchVersion(result.version.id);
      toast.success("Package imported");
    } catch (error) {
      toast.error(error.message);
    } finally {
      setImporting(false);
      event.target.value = "";
    }
  }

  return (
    <>
      <PageHeader title="Repository" actions={<Button disabled={importing} onClick={() => input.current?.click()}><Plus aria-hidden="true" />{importing ? "Importing package…" : "Import package"}</Button>} />
      <input ref={input} type="file" accept=".zip,application/zip" hidden onChange={importPackage} aria-label="Package ZIP" />
      {versions.length ? (
        <section className="skills-tree repository-tree" role="tree" aria-label="Available packages">
          {versions.map((version) => (
            <PackageBranch
              key={version.id}
              version={version}
              initiallyOpen={version.id === versionId}
              onDelete={removePackage}
            />
          ))}
        </section>
      ) : (
        <EmptyState icon={Boxes} title="No packages available" description="Import a package ZIP to browse its repository content." />
      )}
    </>
  );
}
