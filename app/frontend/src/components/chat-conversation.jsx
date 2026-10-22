// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  LoaderCircle,
  MessageSquare,
  SendHorizontal,
  SlidersHorizontal,
  User,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link, useNavigate } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import { LoadingState, PageError } from "@/components/feedback";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { usePackage } from "@/context/package-context";
import { api, streamAgUi } from "@/lib/api";
import { loadedChatThreadId } from "@/lib/chat-thread";

import { ReasoningTimeline } from "@/components/prism/reasoning-timeline";
import { applyPlannerSnapshot, completePlanner, failRunningTools, visibleMessages } from "@/lib/chat-planner";

function formatToolValue(value, fallback) {
  if (!value) return fallback;
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

function ToolsDialog({ tools, enabled, onToggle, disabled }) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button type="button" variant="ghost" className="chat-composer-tools" disabled={disabled}>
          <SlidersHorizontal aria-hidden="true" />
          Tools
          <span>{enabled.size}</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="chat-tools-dialog">
        <DialogHeader>
          <DialogTitle>Available tools</DialogTitle>
          <DialogDescription>Choose which MCP tools this chat may call.</DialogDescription>
        </DialogHeader>
        <div className="chat-tools-modal-list">
          {tools.map((tool) => (
            <label className="chat-tools-modal-item" key={tool.name}>
              <span>
                <strong>{tool.name}</strong>
                <small>{tool.description || "MCP tool"}</small>
              </span>
              <Checkbox
                checked={enabled.has(tool.name)}
                onChange={() => onToggle(tool.name)}
                disabled={disabled}
              />
            </label>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ConversationItem({ item }) {
  if (item.role === "tool-activity") {
    const complete = item.status === "complete";
    if (item.name === "planner") {
      const result = item.result;
      const label = { completed: "Result released", planning_only: "Plan ready", clarification_required: "More information needed", blocked: "Work blocked", failed: "Planner failed" }[result?.status]
        || (item.status === "running" ? "Planner running…" : "Planner failed");
      return <section className="chat-planner" aria-label="Planner activity">
        <h3>{label}</h3>
        {item.reasoning && <ReasoningTimeline entries={item.reasoning.entries} runState={item.reasoning.state} />}
        {item.error && <p role="alert">{item.error}</p>}
        {result?.error && <p role="alert">{result.error}</p>}
        {result?.blockers?.map((text, i) => <p key={i}>{text}</p>)}
        {result?.questions?.map((question, i) => <p key={i}>{typeof question === "string" ? question : question.question || question.prompt || JSON.stringify(question)}</p>)}
        {result?.released_artifact != null && <section aria-label="Released result"><h4>Released result</h4><pre>{typeof result.released_artifact === "string" ? result.released_artifact : JSON.stringify(result.released_artifact, null, 2)}</pre></section>}
        {result?.report?.url && <a href={result.report.url}>Open report</a>}
        {result?.publication_error && <p>{result.publication_error}</p>}
        {result?.status === "planning_only" && <details><summary>Plan</summary><pre>{JSON.stringify(result.plan, null, 2)}</pre></details>}
      </section>;
    }
    return (
      <details className="chat-tool-activity">
        <summary>
          <span className="chat-tool-status">{complete ? <CheckCircle2 aria-hidden="true" /> : <LoaderCircle className="spin" aria-hidden="true" />}</span>
          <span className="chat-tool-title"><strong>{item.name}</strong><small>{complete ? "Tool completed" : "Calling MCP tool…"}</small></span>
          <ChevronDown className="chat-tool-chevron" aria-hidden="true" />
        </summary>
        <div className="chat-tool-details">
          <section>
            <strong>Input</strong>
            <pre>{formatToolValue(item.input, "{}")}</pre>
          </section>
          <section>
            <strong>Output</strong>
            <pre>{formatToolValue(item.output, complete ? "No output" : "Waiting for output…")}</pre>
          </section>
        </div>
      </details>
    );
  }
  const assistant = item.role === "assistant";
  return (
    <article className={`chat-message ${assistant ? "assistant" : "user"}`}>
      <span className="chat-avatar">{assistant ? <Bot aria-hidden="true" /> : <User aria-hidden="true" />}</span>
      <div>
        <strong className="chat-message-author">{assistant ? "Lunar" : "You"}</strong>
        {assistant ? (
          <div className="chat-message-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown>
          </div>
        ) : <p>{item.content}</p>}
      </div>
    </article>
  );
}

export function ChatConversation({ id, reportContext = null }) {
  const navigate = useNavigate();
  const { selected } = usePackage();
  const [models, setModels] = useState([]);
  const [tools, setTools] = useState([]);
  const [modelId, setModelId] = useState("");
  const [enabledTools, setEnabledTools] = useState(new Set());
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [configurationLoading, setConfigurationLoading] = useState(true);
  const [chatLoading, setChatLoading] = useState(Boolean(id));
  const threadId = useRef(crypto.randomUUID());
  const chatId = useRef(null);
  const protocolMessages = useRef([]);
  const conversationEnd = useRef(null);

  useEffect(() => {
    Promise.all([api("/api/ai-models"), reportContext ? Promise.resolve([]) : api("/api/chat/tools")])
      .then(([modelData, toolData]) => {
        setModels(modelData);
        const availableTools = selected?.runtime_state === "ready" ? toolData : toolData.filter((tool) => tool.name !== "planner");
        setTools(availableTools);
        setModelId(modelData[0]?.id || "");
        setEnabledTools(new Set(availableTools.filter((tool) => tool.default_enabled).map((tool) => tool.name)));
      })
      .catch(setError)
      .finally(() => setConfigurationLoading(false));
  }, [reportContext, selected?.runtime_state]);

  useEffect(() => {
    const activeChatId = chatId.current;
    if (id && id === activeChatId) return;
    setRunning(false);
    chatId.current = id || null;
    setError(null);
    if (!id) {
      protocolMessages.current = reportContext ? [{ id: crypto.randomUUID(), role: "system", content: reportContext }] : [];
      threadId.current = crypto.randomUUID();
      setMessages([]);
      setChatLoading(false);
      return;
    }
    setChatLoading(true);
    api(`/api/chats/${id}`)
      .then((chat) => {
        protocolMessages.current = chat.messages;
        threadId.current = loadedChatThreadId(
          chat,
          activeChatId,
          threadId.current,
          crypto.randomUUID(),
        );
        setMessages(visibleMessages(chat.messages));
      })
      .catch(setError)
      .finally(() => setChatLoading(false));
  }, [id, reportContext]);

  useEffect(() => {
    conversationEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);

  useEffect(() => {
    if (reportContext) return;
    const resetChat = () => {
      setRunning(false);
      protocolMessages.current = [];
      threadId.current = crypto.randomUUID();
      setMessages([]);
      setDraft("");
      setError(null);
      chatId.current = null;
    };
    window.addEventListener("new-chat", resetChat);
    return () => window.removeEventListener("new-chat", resetChat);
  }, [reportContext, selected?.runtime_state]);

  function toggleTool(name) {
    setEnabledTools((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function handleEvent(event) {
    if (event.type === "TEXT_MESSAGE_START") {
      protocolMessages.current.push({ id: event.messageId, role: "assistant", content: "" });
    }
    if (event.type === "TEXT_MESSAGE_CONTENT") {
      const protocolMessage = protocolMessages.current.find((item) => item.id === event.messageId);
      if (protocolMessage) protocolMessage.content += event.delta;
      setMessages((current) => {
        const existing = current.findIndex((item) => item.id === event.messageId);
        if (existing === -1) {
          return [...current, { id: event.messageId, role: "assistant", content: event.delta }];
        }
        return current.map((item, index) => index === existing ? { ...item, content: item.content + event.delta } : item);
      });
    }
    if (event.type === "TOOL_CALL_START") {
      const parent = protocolMessages.current.find((item) => item.id === event.parentMessageId);
      if (parent) {
        parent.toolCalls = [
          ...(parent.toolCalls || []),
          { id: event.toolCallId, type: "function", function: { name: event.toolCallName, arguments: "" } },
        ];
      }
      setMessages((current) => [
        ...current,
        { id: event.toolCallId, role: "tool-activity", name: event.toolCallName, status: "running", input: "", output: "" },
      ]);
    }
    if (event.type === "TOOL_CALL_ARGS") {
      for (const message of protocolMessages.current) {
        const toolCall = message.toolCalls?.find((item) => item.id === event.toolCallId);
        if (toolCall) toolCall.function.arguments += event.delta;
      }
      setMessages((current) => current.map((item) => item.id === event.toolCallId ? { ...item, input: item.input + event.delta } : item));
    }
    if (event.type === "TOOL_CALL_RESULT") {
      protocolMessages.current.push({
        id: event.messageId,
        role: "tool",
        toolCallId: event.toolCallId,
        content: event.content,
      });
      setMessages((current) => current.map((item) => item.id === event.toolCallId ? completePlanner(item, event.content) : item));
    }
    if (event.type === "CUSTOM" && event.name === "chat_saved") {
      window.dispatchEvent(new Event("chat-history-updated"));
      chatId.current = event.value?.id || chatId.current;
      if (!reportContext && event.value?.id && event.value.id !== id) {
        navigate(`/chat/${event.value.id}`, { replace: true });
      }
    }
    if (event.type === "CUSTOM" && event.name === "planner_reasoning") {
      setMessages((current) => applyPlannerSnapshot(current, event.value));
    }
    if (event.type === "RUN_ERROR") {
      setMessages((current) => failRunningTools(current, event.message || "Chat stream failed"));
    }
  }

  async function send(event) {
    event?.preventDefault();
    const content = draft.trim();
    if (!content || running) return;
    if (!modelId) {
      toast.error("Choose an AI model first");
      return;
    }

    const userMessage = { id: crypto.randomUUID(), role: "user", content };
    protocolMessages.current.push(userMessage);
    setMessages((current) => [...current, userMessage]);
    setDraft("");
    setRunning(true);
    const sendingThread = threadId.current;
    try {
      await streamAgUi(
        {
          threadId: threadId.current,
          runId: crypto.randomUUID(),
          state: {},
          messages: protocolMessages.current,
          tools: [],
          context: [],
          forwardedProps: {
            aiModelId: modelId,
            chatId: chatId.current || undefined,
            enabledTools: [...enabledTools],
          },
        },
        (event) => { if (threadId.current === sendingThread) handleEvent(event); },
      );
    } catch (requestError) {
      if (threadId.current === sendingThread) {
        setMessages((current) => failRunningTools(current, requestError.message));
        toast.error(requestError.message);
      }
    } finally {
      if (threadId.current === sendingThread) setRunning(false);
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send();
    }
  }

  if (error) return <PageError error={error} />;
  if (configurationLoading || chatLoading) return <LoadingState />;

  const modelItems = models.map((model) => ({
    label: `${model.name} · ${model.model_id}`,
    value: model.id,
  }));

  return (
    <div className="chat-page">
      <div className="chat-layout">
        <section className="chat-panel">
          <div className="chat-toolbar">
            <Select items={modelItems} value={modelId || null} onValueChange={(value) => setModelId(value || "")} disabled={running}>
              <SelectTrigger aria-label="AI model">
                <SelectValue placeholder="Select a model…" />
              </SelectTrigger>
              <SelectContent>
                {modelItems.map((model) => <SelectItem key={model.value} value={model.value}>{model.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="chat-conversation" aria-live="polite">
            {!messages.length && (
              <div className="chat-empty">
                <span><MessageSquare aria-hidden="true" /></span>
                <h2>{reportContext ? "Explore this report" : "Start a conversation"}</h2>
                <p>{reportContext ? "Ask about findings, evidence, or limitations. The report is included as context." : "Ask Lunar a question."}</p>
              </div>
            )}
            {messages.map((item) => <ConversationItem key={item.id} item={item} />)}
            <div ref={conversationEnd} />
          </div>
          <form className="chat-composer" onSubmit={send}>
            {!models.length && <p className="chat-model-warning">Add an <Link to="/ai-models">AI model connection</Link> before chatting.</p>}
            <div className="chat-composer-card">
              <Textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={reportContext ? "Ask about this report…" : "Search"}
                aria-label="Chat message"
                disabled={running || !models.length}
              />
              <div className="chat-composer-actions">
                {!reportContext && <ToolsDialog
                  tools={tools}
                  enabled={enabledTools}
                  onToggle={toggleTool}
                  disabled={running}
                />}
                <Button className="chat-composer-send" type="submit" disabled={running || !draft.trim() || !modelId}>
                  Send
                  {running ? <LoaderCircle className="spin" aria-hidden="true" /> : <SendHorizontal strokeWidth={3} aria-hidden="true" />}
                </Button>
              </div>
            </div>
          </form>
        </section>
      </div>
    </div>
  );
}
