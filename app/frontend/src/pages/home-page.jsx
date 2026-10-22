// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { Brain, Copy, Eye, EyeOff, FileText, LayoutTemplate, ScrollText, Terminal } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { usePackage } from "@/context/package-context";
import { useAuth } from "@/context/auth-context";

const stats = [
  { href: "/prompts", title: "AI Prompts", description: "Write, organize, and test prompts", icon: ScrollText },
  { href: "/reports", title: "Reports", description: "Create and edit versioned reports", icon: FileText },
  { href: "/templates", title: "Templates", description: "Maintain reusable report structures", icon: LayoutTemplate },
  { href: "/ai-models", title: "AI Models", description: "Configure encrypted provider access", icon: Brain },
];

const serverName = "lunar";
const tokenEnvironmentVariable = "LUNAR_MCP_TOKEN";

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

function CopyField({ label, value, description, secret = false, onCopy }) {
  const [revealed, setRevealed] = useState(false);
  const visibleValue = secret && !revealed ? "•".repeat(24) : value;

  return (
    <div className="connection-field">
      <div className="connection-field-label">
        <strong>{label}</strong>
        <small>{description}</small>
      </div>
      <div className="connection-value">
        <code className={secret && !revealed ? "secret-value" : undefined}>{visibleValue}</code>
        {secret && (
          <Button variant="ghost" size="icon" onClick={() => setRevealed((current) => !current)} aria-label={revealed ? "Hide token" : "Show token"}>
            {revealed ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={() => onCopy(value, `${label} copied`)}>
          <Copy aria-hidden="true" />Copy
        </Button>
      </div>
    </div>
  );
}

export function HomePage() {
  const { user } = useAuth();
  const { versionId } = usePackage();
  const mcpUrl = user.mcp_url + (versionId ? `?package_version_id=${encodeURIComponent(versionId)}` : "");
  const cliCommand = `export ${tokenEnvironmentVariable}=${shellQuote(user.mcp_token)}\ncodex mcp add ${serverName} --url ${shellQuote(mcpUrl)} --bearer-token-env-var ${tokenEnvironmentVariable}`;

  async function copy(value, message) {
    await navigator.clipboard.writeText(value);
    toast.success(message);
  }

  return (
    <>
      <p role="status">Import and select a domain package to browse its resources and plan work.</p>
      <div className="stats-grid">
        {stats.map(({ href, title, description, icon: Icon }) => (
          <Link key={href} to={href} className="card stat-card">
            <span><Icon aria-hidden="true" /></span><strong>{title}</strong><small>{description}</small>
          </Link>
        ))}
      </div>
      <Card className="connection-card">
        <div className="connection-heading">
          <div>
            <p className="eyebrow">MCP connection</p>
            <h2>Connect your MCP client to Lunar</h2>
          </div>
        </div>

        <div className="connection-steps">
          <section className="connection-step">
            <span className="step-number">1</span>
            <CopyField label="Name" value={serverName} description="Paste into the Name field." onCopy={copy} />
          </section>

          <section className="connection-step">
            <span className="step-number">2</span>
            <div className="connection-field">
              <div className="connection-field-label">
                <strong>Type</strong>
                <small>Lunar is a remote server. Choose Streamable HTTP, not STDIO.</small>
              </div>
              <div className="transport-picker" aria-label="Select Streamable HTTP">
                <span>STDIO</span><strong>Streamable HTTP</strong>
              </div>
            </div>
          </section>

          <section className="connection-step">
            <span className="step-number">3</span>
            <CopyField label="URL" value={mcpUrl} description="Paste into the Server URL field." onCopy={copy} />
          </section>

          <section className="connection-step">
            <span className="step-number">4</span>
            <div className="connection-field authentication-fields">
              <div className="connection-field-label">
                <strong>Bearer token authentication</strong>
                <small>Your MCP client reads the token from a local environment variable.</small>
              </div>
              <CopyField
                label="Environment variable name"
                value={tokenEnvironmentVariable}
                description="Paste this name into the Bearer token environment variable field."
                onCopy={copy}
              />
              <CopyField
                label="Environment variable value"
                value={user.mcp_token}
                description={`Set ${tokenEnvironmentVariable} to this private token before restarting your client.`}
                secret
                onCopy={copy}
              />
            </div>
          </section>
        </div>

        <div className="cli-setup">
          <div className="cli-heading">
            <div>
              <p className="eyebrow"><Terminal aria-hidden="true" />Command line</p>
              <h3>Or set it up from your terminal</h3>
              <p>Copy and run both commands in the same terminal session.</p>
            </div>
            <Button variant="outline" size="sm" onClick={() => copy(cliCommand, "Setup command copied")}>
              <Copy aria-hidden="true" />Copy command
            </Button>
          </div>
          <pre>{cliCommand}</pre>
        </div>

      </Card>
    </>
  );
}
