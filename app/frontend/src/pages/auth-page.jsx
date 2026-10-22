// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import { useState } from "react";
import { Navigate, NavLink, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/auth-context";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export function AuthPage({ mode }) {
  const signup = mode === "signup";
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const data = await api(`/api/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(form))),
      });
      if (signup) {
        setNotice(data.message);
        form.reset();
        return;
      }
      const session = await api("/api/auth/me");
      setUser(session.user);
      navigate("/", { replace: true });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-wrap">
        <img src="/logo.png" className="auth-logo" alt="Lunar" />
        <Card className="auth-card">
          <h1>{signup ? "Create your account" : "Welcome back"}</h1>
          <nav className="tabs" aria-label="Authentication">
            <NavLink to="/signin" className={({ isActive }) => cn(isActive && "active")}>Sign in</NavLink>
            <NavLink to="/signup" className={({ isActive }) => cn(isActive && "active")}>Create account</NavLink>
          </nav>
          <form className="form-stack" onSubmit={submit}>
            <Label>Email<Input name="email" type="email" autoComplete="email" required /></Label>
            <Label>Password<Input name="password" type="password" minLength={signup ? 8 : 1} required /></Label>
            {error && <p className="form-error">{error}</p>}
            {notice && <p className="form-success">{notice}</p>}
            <Button type="submit" disabled={submitting}>{submitting ? "Working…" : signup ? "Create account" : "Sign in"}</Button>
          </form>
        </Card>
      </section>
    </main>
  );
}
