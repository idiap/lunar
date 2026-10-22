// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";

let engine;
function mathEngine() {
  if (!engine) engine = new Promise((resolve, reject) => {
    window.MathJax = { startup: { typeset: false }, svg: { fontCache: "none" },
      options: { enableMenu: false } };
    const script = document.createElement("script");
    script.src = "/mathjax/tex-svg.js";
    script.onload = () => window.MathJax.startup.promise.then(() => resolve(window.MathJax), reject);
    script.onerror = () => { engine = null; script.remove(); reject(new Error("Equation renderer unavailable")); };
    document.head.append(script);
  });
  return engine;
}

// The TeX engine returns SVG. Remove active content and nonlocal URLs before
// inserting it into the application document; source HTML is never admitted.
function safeSvg(node) {
  node.querySelectorAll("script,foreignObject,iframe,object,embed,style").forEach((item) => item.remove());
  for (const item of [node, ...node.querySelectorAll("*")]) {
    for (const attribute of [...item.attributes]) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || (name === "style" && /url\s*\(|expression\s*\(/i.test(attribute.value)) || (["href", "xlink:href"].includes(name) && !attribute.value.startsWith("#"))) item.removeAttribute(attribute.name);
    }
  }
  return node.outerHTML;
}

export function ReportMath({ tex, display = false }) {
  const [rendered, setRendered] = useState(null);
  useEffect(() => {
    let active = true;
    setRendered(null);
    mathEngine().then((math) => math.tex2svgPromise(tex, { display }))
      .then((node) => { if (active) setRendered(safeSvg(node)); })
      .catch(() => { if (active) setRendered(null); });
    return () => { active = false; };
  }, [tex, display]);
  return <span className={display ? "report-math display" : "report-math"} role="math" aria-label={tex}>
    {rendered ? <span dangerouslySetInnerHTML={{ __html: rendered }} /> : <code>{tex}</code>}
  </span>;
}

export function ReportInlineCode({ children, className, node: _node, ...props }) {
  const value = String(children).replace(/\n$/, "");
  if (value.startsWith("$$") && value.endsWith("$$")) return <ReportMath tex={value.slice(2, -2)} display />;
  if (value.startsWith("$") && value.endsWith("$")) return <ReportMath tex={value.slice(1, -1)} />;
  return <code className={className} {...props}>{children}</code>;
}
