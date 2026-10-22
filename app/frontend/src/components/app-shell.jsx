// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import {
  Brain,
  BookOpen,
  Database,
  FileText,
  FolderGit2,
  Home,
  LayoutTemplate,
  LogOut,
  MessageSquare,
  MoreVertical,
  Plus,
  ScrollText,
  Trash2,
  Workflow,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { PackageSwitcher } from "@/components/package-switcher";
import { usePackage } from "@/context/package-context";
import { LoadingState, PageError } from "@/components/feedback";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/auth-context";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const navigation = [
  { href: "/", label: "Home", icon: Home, end: true },
  { href: "/chat", label: "Chat", icon: MessageSquare },
  { href: "/data-sources", label: "Data Sources", icon: Database },
  { href: "/prompts", label: "AI Prompts", icon: ScrollText },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/templates", label: "Templates", icon: LayoutTemplate },
  { href: "/ai-models", label: "AI Models", icon: Brain },
  { href: "/repository", label: "Repository", icon: FolderGit2 },
  { href: "/prism", label: "Prism", icon: Workflow },
  { href: "/skills", label: "Skills", icon: BookOpen },
];

function relativeCreatedAt(value) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return `${Math.floor(seconds / 604800)}w ago`;
}

export function AppShell() {
  const { user, setUser } = useAuth();
  const { versionId, restoring, error } = usePackage();
  const location = useLocation();
  const navigate = useNavigate();
  const [chats, setChats] = useState([]);
  const [openMenuId, setOpenMenuId] = useState(null);
  const inChat = location.pathname === "/chat" || location.pathname.startsWith("/chat/");
  const inPrism = location.pathname === "/prism";

  useEffect(() => {
    if (!inChat) {
      setChats([]);
      return undefined;
    }
    let active = true;
    const loadChats = () => {
      api("/api/chats")
        .then((items) => { if (active) setChats(items); })
        .catch(() => { if (active) setChats([]); });
    };
    loadChats();
    window.addEventListener("chat-history-updated", loadChats);
    return () => {
      active = false;
      window.removeEventListener("chat-history-updated", loadChats);
    };
  }, [inChat, versionId]);

  useEffect(() => {
    const closeMenu = (event) => {
      if (event.type === "keydown" && event.key !== "Escape") return;
      if (event.type === "pointerdown" && event.target.closest(".sidebar-chat-actions")) return;
      setOpenMenuId(null);
    };
    document.addEventListener("pointerdown", closeMenu);
    document.addEventListener("keydown", closeMenu);
    return () => {
      document.removeEventListener("pointerdown", closeMenu);
      document.removeEventListener("keydown", closeMenu);
    };
  }, []);

  async function signOut() {
    await api("/api/auth/signout", { method: "POST" });
    setUser(null);
    navigate("/signin", { replace: true });
  }

  function newChat() {
    navigate("/chat");
    window.dispatchEvent(new Event("new-chat"));
  }

  async function deleteChat(chat) {
    setOpenMenuId(null);
    try {
      await api(`/api/chats/${chat.id}`, { method: "DELETE" });
      setChats((current) => current.filter((item) => item.id !== chat.id));
      if (location.pathname === `/chat/${chat.id}`) newChat();
      toast.success("Chat deleted");
    } catch (error) {
      toast.error(error.message);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand" aria-label="Lunar home">
          <img src="/logo.png" alt="Lunar" />
        </NavLink>
        <PackageSwitcher />
        <nav aria-label="Primary navigation">
          {navigation.map(({ href, label, icon: Icon, end }) => (
            <NavLink
              key={href}
              to={href}
              end={end}
              className={({ isActive }) => cn("nav-item", isActive && "active")}
            >
              <span className="nav-icon"><Icon aria-hidden="true" /></span>
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        {inChat && (
          <section className="sidebar-chats" aria-label="Saved chats">
            <div className="sidebar-chats-heading">
              <p>Chats</p>
              <button type="button" onClick={newChat} aria-label="Start a new chat" title="New chat">
                <Plus aria-hidden="true" />
              </button>
            </div>
            <div className="sidebar-chat-list">
              {chats.filter((chat) => (chat.version_id || null) === versionId).map((chat) => (
                <div className="sidebar-chat-row" key={chat.id}>
                  <NavLink to={`/chat/${chat.id}`} className="sidebar-chat">
                    <span>{chat.title}</span>
                    <time dateTime={chat.created_at}>{relativeCreatedAt(chat.created_at)}</time>
                  </NavLink>
                  <div className="sidebar-chat-actions">
                    <button
                      type="button"
                      className="sidebar-chat-menu-trigger"
                      aria-label={`Chat options for ${chat.title}`}
                      aria-haspopup="menu"
                      aria-expanded={openMenuId === chat.id}
                      onClick={() => setOpenMenuId((current) => current === chat.id ? null : chat.id)}
                    >
                      <MoreVertical aria-hidden="true" />
                    </button>
                    {openMenuId === chat.id && (
                      <div className="sidebar-chat-menu" role="menu">
                        <button type="button" role="menuitem" onClick={() => deleteChat(chat)}>
                          <Trash2 aria-hidden="true" />
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {!chats.length && <small>No saved chats yet</small>}
            </div>
          </section>
        )}
        <div className="account">
          <span className="avatar">{user.email[0].toUpperCase()}</span>
          <span className="account-email">{user.email}</span>
          <Button variant="ghost" size="icon" onClick={signOut} title="Sign out" aria-label="Sign out">
            <LogOut aria-hidden="true" />
          </Button>
        </div>
      </aside>
      <main className={cn("main-content", inChat && "chat-main", inPrism && "prism-main")}>{restoring ? <LoadingState label="Restoring workspace…" /> : error ? <PageError error={error} /> : !versionId && /^\/(skills|data-sources|reports|prism)(\/|$)/.test(location.pathname) ? <p>Select or import a package to open this view.</p> : <Outlet key={`${user.id}:${versionId || "none"}`} />}</main>
    </div>
  );
}
