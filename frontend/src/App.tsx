import { useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askQuestionStream, deleteDocument, listDocuments, searchDocuments, uploadDocument } from "./api";
import type { AskResponse, DocumentInfo, SearchMode, SearchResponse, Source } from "./types";

const suggestions = [
  { title: "Get the big picture", prompt: "Summarize this document" },
  { title: "Pull out key facts", prompt: "What are the most important points I should know?" },
  { title: "Check a specific detail", prompt: "What is the password policy?" },
];

const thinkingSteps = [
  "Looking through your documents…",
  "Reading the most relevant passages…",
  "Writing your answer…",
];

const matchOptions: { value: SearchMode; label: string; hint: string }[] = [
  { value: "reranked", label: "Best match (recommended)", hint: "Finds passages and double-checks which fit your question best." },
  { value: "hybrid", label: "Meaning + exact words", hint: "Combines both approaches below." },
  { value: "semantic", label: "Similar meaning", hint: "Finds passages that mean the same thing, even with different words." },
  { value: "keyword", label: "Exact words", hint: "Only finds passages containing your exact words." },
];

const allowedExtensions = [".pdf", ".docx", ".txt"];
const CHATS_KEY = "atlas.chats";
const SELECTION_KEY = "atlas.selectedDocuments";
const MAX_CHATS = 20;

type Turn = {
  id: number;
  question: string;
  kind: "ask" | "find";
  status: "loading" | "done" | "error";
  scope: string[];
  answer?: AskResponse;
  results?: SearchResponse;
  error?: string;
};

type Chat = {
  id: string;
  title: string;
  updatedAt: number;
  turns: Turn[];
};

type Upload = {
  name: string;
  status: "uploading" | "failed";
  message?: string;
};

function loadJson<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return value ? (JSON.parse(value) as T) : fallback;
  } catch {
    return fallback;
  }
}

function saveChats(chats: Chat[]) {
  // Drop the oldest chats if the browser's storage quota is exceeded.
  for (let count = chats.length; count >= 0; count--) {
    try {
      localStorage.setItem(CHATS_KEY, JSON.stringify(chats.slice(0, count)));
      return;
    } catch {
      // Try again with fewer chats.
    }
  }
}

const newChatId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

function App() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<Turn["kind"]>("ask");
  const [mode, setMode] = useState<SearchMode>("reranked");
  const [topK, setTopK] = useState(5);
  const [chats, setChats] = useState<Chat[]>(() => loadJson<Chat[]>(CHATS_KEY, []));
  const [chatId, setChatId] = useState(newChatId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null);
  const [documentsError, setDocumentsError] = useState("");
  const [selected, setSelected] = useState<string[]>(() => loadJson<string[]>(SELECTION_KEY, []));
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [notice, setNotice] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const busy = turns.some((turn) => turn.status === "loading" || turn.answer?.streaming);
  const readyDocuments = (documents ?? []).filter((doc) => doc.chunks > 0);
  const nameOf = (id: string) => documents?.find((doc) => doc.document_id === id)?.filename ?? "a removed document";

  useEffect(() => {
    refreshDocuments();
  }, []);

  useEffect(() => {
    localStorage.setItem(SELECTION_KEY, JSON.stringify(selected));
  }, [selected]);

  useEffect(() => {
    saveChats(chats);
  }, [chats]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  // Keep the active conversation in the history list once answers finish.
  useEffect(() => {
    if (busy) return;
    const finished = turns.filter((turn) => turn.status !== "loading");
    if (finished.length === 0) return;
    setChats((current) => [
      { id: chatId, title: finished[0].question, updatedAt: Date.now(), turns: finished },
      ...current.filter((chat) => chat.id !== chatId),
    ].slice(0, MAX_CHATS));
  }, [turns, chatId, busy]);

  async function refreshDocuments() {
    try {
      const list = await listDocuments();
      setDocuments(list);
      setDocumentsError("");
      // Forget selections for documents that no longer exist.
      setSelected((current) => current.filter((id) => list.some((doc) => doc.document_id === id && doc.chunks > 0)));
    } catch (requestError) {
      setDocumentsError(requestError instanceof Error ? requestError.message : "Couldn't load your documents.");
    }
  }

  function startNewChat() {
    setChatId(newChatId());
    setTurns([]);
    inputRef.current?.focus();
  }

  function openChat(chat: Chat) {
    setChatId(chat.id);
    setTurns(chat.turns);
  }

  function removeChat(id: string) {
    setChats((current) => current.filter((chat) => chat.id !== id));
    if (id === chatId) startNewChat();
  }

  async function submit(text = query) {
    const question = text.trim();
    if (question.length < 3 || busy) return;

    const id = Date.now();
    const turnKind = kind;
    const scope = [...selected];
    setTurns((current) => [...current, { id, question, kind: turnKind, status: "loading", scope }]);
    setQuery("");

    const update = (patch: Partial<Turn>) =>
      setTurns((current) => current.map((turn) => (turn.id === id ? { ...turn, ...patch } : turn)));

    try {
      if (turnKind === "ask") {
        await askQuestionStream(question, topK, scope, (partial) => {
          // Show the answer as soon as the first words arrive.
          if (partial.answer) update({ status: "done", answer: partial });
        });
      } else {
        update({ status: "done", results: await searchDocuments(question, topK, mode, scope) });
      }
    } catch (requestError) {
      update({
        status: "error",
        error: requestError instanceof Error ? requestError.message : "Something went wrong. Please try again.",
      });
    }
  }

  async function addFile(file?: File) {
    if (!file) return;
    const name = file.name;
    const extension = name.slice(name.lastIndexOf(".")).toLowerCase();
    const setUpload = (upload: Upload | null) =>
      setUploads((current) => [...(upload ? [upload] : []), ...current.filter((item) => item.name !== name)]);

    if (!allowedExtensions.includes(extension)) {
      setUpload({ name, status: "failed", message: "I can only read PDF, Word (.docx), and text (.txt) files." });
      return;
    }

    setUpload({ name, status: "uploading" });
    try {
      const result = await uploadDocument(file);
      setUpload(null);
      await refreshDocuments();
      // Focus answers on the document that was just added.
      setSelected([result.document_id]);
      setNotice(
        result.status === "duplicate"
          ? `You've already added this file, so I'm using the existing copy of “${result.filename}”. Answers will come from it only.`
          : `“${result.filename}” is ready. Answers will now come from this document only. Tick other documents to include them too.`,
      );
    } catch (requestError) {
      setUpload({
        name,
        status: "failed",
        message: requestError instanceof Error ? requestError.message : "Upload failed. Please try again.",
      });
    }
  }

  async function removeDocument(doc: DocumentInfo) {
    if (!window.confirm(`Remove “${doc.filename}”? It will no longer be used for answers.`)) return;
    try {
      await deleteDocument(doc.document_id);
      setSelected((current) => current.filter((id) => id !== doc.document_id));
      await refreshDocuments();
    } catch (requestError) {
      setDocumentsError(requestError instanceof Error ? requestError.message : "Couldn't remove that document.");
    }
  }

  function toggleDocument(id: string) {
    setNotice("");
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  return (
    <main className="flex min-h-screen flex-col bg-mist text-ink">
      <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-ink text-lg font-bold text-white">A</div>
            <div>
              <p className="font-semibold leading-tight">Atlas</p>
              <p className="text-xs text-slate-500">Your document assistant</p>
            </div>
          </div>
          {turns.length > 0 && (
            <button className="button-secondary" disabled={busy} onClick={startNewChat}>
              + New chat
            </button>
          )}
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-6xl flex-1 gap-6 px-5 py-6 lg:grid-cols-[300px_minmax(0,1fr)] lg:px-8">
        <aside className="space-y-5 lg:sticky lg:top-24 lg:max-h-[calc(100vh-7rem)] lg:self-start lg:overflow-y-auto">
          <DocumentPanel
            documents={documents}
            error={documentsError}
            uploads={uploads}
            selected={selected}
            notice={notice}
            onFile={addFile}
            onToggle={toggleDocument}
            onUseAll={() => { setNotice(""); setSelected([]); }}
            onRemove={removeDocument}
          />
          <HistoryPanel chats={chats} activeId={chatId} busy={busy} onOpen={openChat} onRemove={removeChat} onNew={startNewChat} />
        </aside>

        <section className="mx-auto flex min-h-[60vh] w-full max-w-3xl flex-col">
          <div className="flex-1 space-y-10 pb-6">
            {turns.length === 0 ? (
              <Welcome hasDocuments={readyDocuments.length > 0} onPick={(prompt) => { setQuery(prompt); inputRef.current?.focus(); }} />
            ) : (
              turns.map((turn) => (
                <TurnView key={turn.id} turn={turn} scopeLabel={scopeLabel(turn.scope ?? [], nameOf)} onRetry={() => submit(turn.question)} />
              ))
            )}
            <div ref={bottomRef} />
          </div>

          <Composer
            inputRef={inputRef}
            query={query}
            setQuery={setQuery}
            kind={kind}
            setKind={setKind}
            mode={mode}
            setMode={setMode}
            topK={topK}
            setTopK={setTopK}
            busy={busy}
            scopeLabel={scopeLabel(selected, nameOf)}
            onSubmit={() => submit()}
          />
        </section>
      </div>
    </main>
  );
}

function scopeLabel(ids: string[], nameOf: (id: string) => string) {
  if (ids.length === 0) return "all documents";
  if (ids.length === 1) return nameOf(ids[0]);
  return `${ids.length} selected documents`;
}

function formatDate(value: string | null) {
  if (!value) return "";
  return new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

type DocumentPanelProps = {
  documents: DocumentInfo[] | null;
  error: string;
  uploads: Upload[];
  selected: string[];
  notice: string;
  onFile: (file?: File) => void;
  onToggle: (id: string) => void;
  onUseAll: () => void;
  onRemove: (doc: DocumentInfo) => void;
};

function DocumentPanel({ documents, error, uploads, selected, notice, onFile, onToggle, onUseAll, onRemove }: DocumentPanelProps) {
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Your documents</p>
        {documents && documents.length > 0 && (
          <span className="text-xs text-slate-400">{documents.length} total</span>
        )}
      </div>
      <button
        type="button"
        className={`mt-3 flex w-full flex-col items-center rounded-2xl border-2 border-dashed px-4 py-5 text-center transition ${dragging ? "border-teal bg-teal/5" : "border-slate-200 hover:border-teal hover:bg-teal/5"}`}
        onClick={() => fileInput.current?.click()}
        onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); Array.from(event.dataTransfer.files).forEach(onFile); }}
      >
        <span className="grid h-9 w-9 place-items-center rounded-full bg-teal/10 text-xl text-teal">+</span>
        <span className="mt-2 text-sm font-medium text-slate-700">Drop a file here or click to browse</span>
        <span className="mt-1 text-xs text-slate-400">PDF, Word, or text files</span>
      </button>
      <input
        ref={fileInput}
        className="hidden"
        type="file"
        multiple
        accept={allowedExtensions.join(",")}
        onChange={(event) => { Array.from(event.target.files ?? []).forEach(onFile); event.target.value = ""; }}
      />

      {uploads.map((upload) => (
        <div key={upload.name} className={`mt-3 rounded-xl px-3 py-2.5 text-xs ${upload.status === "failed" ? "bg-red-50 text-red-700" : "bg-mist text-slate-500"}`}>
          <p className="truncate font-medium" title={upload.name}>{upload.name}</p>
          <p className="mt-0.5 leading-5">{upload.status === "uploading" ? "Reading this file… this can take a minute." : upload.message}</p>
        </div>
      ))}

      {notice && <p className="mt-3 rounded-xl bg-teal/5 px-3 py-2.5 text-xs leading-5 text-teal-800">{notice}</p>}
      {error && <p className="mt-3 rounded-xl bg-red-50 px-3 py-2.5 text-xs leading-5 text-red-700">{error}</p>}

      {documents === null && !error && <p className="mt-4 text-xs text-slate-400">Loading your documents…</p>}
      {documents?.length === 0 && <p className="mt-4 text-xs leading-5 text-slate-500">No documents yet. Add one above to get started.</p>}

      {documents && documents.length > 0 && (
        <>
          <div className="mt-4 flex items-center justify-between text-xs">
            <span className="text-slate-500">
              Asking about: <strong className="font-semibold text-slate-700">{selected.length === 0 ? "all documents" : `${selected.length} selected`}</strong>
            </span>
            {selected.length > 0 && <button className="font-medium text-teal hover:underline" onClick={onUseAll}>Use all</button>}
          </div>
          <ul className="mt-2 max-h-72 space-y-1.5 overflow-y-auto pr-1">
            {documents.map((doc) => {
              const readable = doc.chunks > 0;
              const checked = selected.includes(doc.document_id);
              return (
                <li key={doc.document_id} className={`group flex items-start gap-2.5 rounded-xl px-2.5 py-2 transition ${checked ? "bg-teal/10" : "hover:bg-mist"}`}>
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 shrink-0 accent-teal"
                    checked={checked}
                    disabled={!readable}
                    onChange={() => onToggle(doc.document_id)}
                    aria-label={`Ask about ${doc.filename}`}
                  />
                  <button className="min-w-0 flex-1 text-left" disabled={!readable} onClick={() => onToggle(doc.document_id)}>
                    <p className="truncate text-sm font-medium text-slate-700" title={doc.filename}>{doc.filename}</p>
                    <p className={`text-xs ${readable ? "text-slate-400" : "text-amber-600"}`}>
                      {readable ? `Added ${formatDate(doc.created_at)}` : "No readable text. You can remove it."}
                    </p>
                  </button>
                  <button
                    className="shrink-0 rounded-md px-1.5 py-0.5 text-xs text-slate-400 opacity-60 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100"
                    title="Remove document"
                    onClick={() => onRemove(doc)}
                  >
                    ✕
                  </button>
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-xs leading-5 text-slate-400">Tick documents to focus your questions on them. Leave all unticked to search everything.</p>
        </>
      )}
    </div>
  );
}

type HistoryPanelProps = {
  chats: Chat[];
  activeId: string;
  busy: boolean;
  onOpen: (chat: Chat) => void;
  onRemove: (id: string) => void;
  onNew: () => void;
};

function HistoryPanel({ chats, activeId, busy, onOpen, onRemove, onNew }: HistoryPanelProps) {
  return (
    <div className="card p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold">Recent chats</p>
        <button className="text-xs font-medium text-teal hover:underline disabled:opacity-50" disabled={busy} onClick={onNew}>+ New chat</button>
      </div>
      {chats.length === 0 ? (
        <p className="mt-3 text-xs leading-5 text-slate-500">Your conversations will appear here so you can come back to them later.</p>
      ) : (
        <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto pr-1">
          {chats.map((chat) => (
            <li key={chat.id} className={`group flex items-center gap-2 rounded-xl px-2.5 py-2 transition ${chat.id === activeId ? "bg-teal/10" : "hover:bg-mist"}`}>
              <button className="min-w-0 flex-1 text-left disabled:cursor-not-allowed" disabled={busy} onClick={() => onOpen(chat)}>
                <p className="truncate text-sm text-slate-700" title={chat.title}>{chat.title}</p>
                <p className="text-xs text-slate-400">
                  {chat.turns.length} {chat.turns.length === 1 ? "question" : "questions"} · {new Date(chat.updatedAt).toLocaleDateString(undefined, { day: "numeric", month: "short" })}
                </p>
              </button>
              <button
                className="shrink-0 rounded-md px-1.5 py-0.5 text-xs text-slate-400 opacity-60 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100"
                title="Delete chat"
                onClick={() => onRemove(chat.id)}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs leading-5 text-slate-400">Saved in this browser only.</p>
    </div>
  );
}

function Welcome({ hasDocuments, onPick }: { hasDocuments: boolean; onPick: (prompt: string) => void }) {
  return (
    <div className="card p-6 sm:p-8">
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Hi there 👋 What would you like to know?</h1>
      <p className="mt-3 max-w-2xl text-[15px] leading-7 text-slate-600">
        Ask me anything about your documents. I'll only answer from what's actually written in them, and I'll
        show you exactly where I found it. If the answer isn't there, I'll tell you instead of guessing.
      </p>
      <ol className="mt-5 grid gap-3 text-sm text-slate-600 sm:grid-cols-3">
        <Step number={1}>{hasDocuments ? "Pick documents on the left, or add a new one." : "Add a document on the left."}</Step>
        <Step number={2}>Ask a question in your own words.</Step>
        <Step number={3}>Click the numbers in my answer to see the source.</Step>
      </ol>
      <p className="mt-6 text-sm font-medium text-slate-500">Not sure where to start? Try one of these:</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {suggestions.map((item) => (
          <button key={item.prompt} className="rounded-2xl border border-slate-200 p-4 text-left transition hover:border-teal hover:bg-teal/5" onClick={() => onPick(item.prompt)}>
            <p className="text-sm font-semibold text-slate-700">{item.title}</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">“{item.prompt}”</p>
          </button>
        ))}
      </div>
    </div>
  );
}

function TurnView({ turn, scopeLabel, onRetry }: { turn: Turn; scopeLabel: string; onRetry: () => void }) {
  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-3xl bg-slate-200/70 px-5 py-3 text-[15px] leading-7 text-ink">
          {turn.question}
        </div>
      </div>
      <div className="flex gap-3 sm:gap-4">
        <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ink text-sm font-bold text-white">A</div>
        <div className="min-w-0 flex-1 pt-0.5">
          {turn.status === "loading" && <Thinking kind={turn.kind} />}
          {turn.status === "error" && (
            <div>
              <p className="text-[15px] leading-7 text-slate-700">😕 {turn.error}</p>
              <button className="button-secondary mt-3" onClick={onRetry}>Try again</button>
            </div>
          )}
          {turn.answer && <AnswerView turnId={turn.id} result={turn.answer} scopeLabel={scopeLabel} />}
          {turn.results && <ResultsView result={turn.results} />}
        </div>
      </div>
    </div>
  );
}

function Thinking({ kind }: { kind: Turn["kind"] }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((current) => current + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const step = Math.min(Math.floor(seconds / 2), thinkingSteps.length - 1);

  return (
    <div className="pt-1">
      <div className="flex items-center gap-3 text-[15px] text-slate-500">
        <span className="flex gap-1">
          {[0, 1, 2].map((dot) => <span key={dot} className="h-2 w-2 animate-bounce rounded-full bg-teal" style={{ animationDelay: `${dot * 150}ms` }} />)}
        </span>
        {kind === "ask" ? thinkingSteps[step] : "Searching your documents…"}
      </div>
      {seconds >= 12 && (
        <p className="mt-3 text-xs leading-5 text-slate-400">
          Taking a little longer than usual. If I haven't been used for a while, the server needs up to a minute to wake up. Thanks for your patience!
        </p>
      )}
    </div>
  );
}

function AnswerView({ turnId, result, scopeLabel }: { turnId: number; result: AskResponse; scopeLabel: string }) {
  const [copied, setCopied] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const validation = result.citation_validation;
  const streaming = Boolean(result.streaming);

  function showSource(label: string) {
    setShowSources(true);
    // Wait for the sources list to render before scrolling to it.
    setTimeout(() => {
      const element = document.getElementById(`turn-${turnId}-${label}`);
      if (!element) return;
      element.scrollIntoView({ behavior: "smooth", block: "center" });
      element.classList.add("source-flash");
      setTimeout(() => element.classList.remove("source-flash"), 1600);
    }, 50);
  }

  async function copy() {
    await navigator.clipboard.writeText(result.answer.replace(/\s?\[S\d+(?:\s*,\s*S\d+)*\]/g, ""));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  const cited = new Set(validation.valid_citations);
  const sources = [...result.sources].sort(
    (a, b) => Number(cited.has(b.source_id ?? "")) - Number(cited.has(a.source_id ?? "")),
  );
  const basedOn = result.documents_used?.length ? result.documents_used.join(", ") : scopeLabel;

  return (
    <div>
      <div className="markdown">
        <Markdown text={result.answer} onCite={showSource} />
        {streaming && <span className="streaming-cursor" aria-hidden />}
      </div>

      {!streaming && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            <button className="action-button" onClick={copy}>{copied ? "✓ Copied" : "⧉ Copy"}</button>
            {sources.length > 0 && (
              <button className="action-button" onClick={() => setShowSources(!showSources)}>
                📄 {showSources ? "Hide sources" : `Sources (${cited.size || sources.length})`}
              </button>
            )}
            <TrustNote validation={validation} hasSources={sources.length > 0} />
          </div>
          {sources.length > 0 && (
            <p className="mt-2 truncate text-xs text-slate-400" title={basedOn}>Based on: {basedOn}</p>
          )}

          {showSources && (
            <div className="mt-4 grid gap-3">
              {sources.map((source) => (
                <SourceCard
                  key={source.chunk_id}
                  id={`turn-${turnId}-${source.source_id}`}
                  source={source}
                  label={source.source_id ?? ""}
                  muted={cited.size > 0 && !cited.has(source.source_id ?? "")}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function TrustNote({ validation, hasSources }: { validation: AskResponse["citation_validation"]; hasSources: boolean }) {
  if (!hasSources) {
    return <span className="px-2 text-slate-400">Nothing about this in your documents</span>;
  }
  if (!validation.has_citations) {
    return <span className="px-2 text-slate-400">No references in this answer</span>;
  }
  if (!validation.valid) {
    return <span className="px-2 text-amber-600">⚠ Some references don't match a source; please double-check</span>;
  }
  return <span className="px-2 text-teal">✓ Backed by your documents</span>;
}

// Turn [S1] / [S1, S2] into links that the renderer shows as citation chips.
function linkCitations(text: string) {
  return text.replace(/\[(S\d+(?:\s*,\s*S\d+)*)\]/g, (_match, labels: string) =>
    labels
      .split(/\s*,\s*/)
      .map((label) => `[${label.slice(1)}](#cite-${label})`)
      .join(""),
  );
}

function Markdown({ text, onCite }: { text: string; onCite: (label: string) => void }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) =>
          href?.startsWith("#cite-") ? (
            <button className="cite" title="Show where this came from" onClick={() => onCite(href.slice("#cite-".length))}>
              {children}
            </button>
          ) : (
            <a href={href} target="_blank" rel="noreferrer">{children}</a>
          ),
        table: ({ children }) => (
          <div className="table-wrap"><table>{children}</table></div>
        ),
      }}
    >
      {linkCitations(text)}
    </ReactMarkdown>
  );
}

function ResultsView({ result }: { result: SearchResponse }) {
  if (result.results.length === 0) {
    return <p className="text-[15px] leading-7 text-slate-700">I couldn't find any passages matching that. Try different words, or switch to “Get an answer”.</p>;
  }
  return (
    <div>
      <p className="text-[15px] leading-7 text-slate-700">
        Here are the {result.results.length} passages that best match your question, most relevant first:
      </p>
      <div className="mt-4 grid gap-3">
        {result.results.map((source, index) => (
          <SourceCard key={source.chunk_id} source={source} label={index === 0 ? "Top match" : `#${index + 1}`} />
        ))}
      </div>
    </div>
  );
}

function SourceCard({ source, label, id, muted = false }: { source: Source; label: string; id?: string; muted?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const isCitation = /^S\d+$/.test(label);

  return (
    <article id={id} className={`rounded-2xl border border-slate-200 bg-mist/60 p-4 transition ${muted ? "opacity-60" : ""}`}>
      <div className="flex items-center gap-2">
        <span className={isCitation ? "cite cite-static" : "source-label"}>{isCitation ? label.slice(1) : label}</span>
        <p className="truncate text-sm font-semibold text-slate-700" title={source.filename}>📄 {source.filename}</p>
        <span className="ml-auto shrink-0 text-xs text-slate-400">Section {source.chunk_index + 1}</span>
      </div>
      {source.content && (
        <>
          <p className={`mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600 ${expanded ? "" : "line-clamp-4"}`}>{source.content}</p>
          {source.content.length > 300 && (
            <button className="mt-1 text-xs font-medium text-teal hover:underline" onClick={() => setExpanded(!expanded)}>
              {expanded ? "Show less" : "Read full passage"}
            </button>
          )}
        </>
      )}
      {muted && <p className="mt-2 text-xs text-slate-400">Checked, but not used in the answer.</p>}
    </article>
  );
}

type ComposerProps = {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  query: string;
  setQuery: (value: string) => void;
  kind: Turn["kind"];
  setKind: (value: Turn["kind"]) => void;
  mode: SearchMode;
  setMode: (value: SearchMode) => void;
  topK: number;
  setTopK: (value: number) => void;
  busy: boolean;
  scopeLabel: string;
  onSubmit: () => void;
};

function Composer({ inputRef, query, setQuery, kind, setKind, mode, setMode, topK, setTopK, busy, scopeLabel, onSubmit }: ComposerProps) {
  const tooShort = query.trim().length < 3;

  // Grow the input with its content, up to a limit.
  useEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
  }, [query, inputRef]);

  return (
    <div className="sticky bottom-0 -mx-1 bg-gradient-to-t from-mist via-mist to-mist/0 px-1 pb-3 pt-6">
      <div className="rounded-[28px] border border-slate-200 bg-white px-3 pb-2 pt-2 shadow-card focus-within:border-slate-300">
        <textarea
          ref={inputRef}
          rows={1}
          className="max-h-[200px] w-full resize-none bg-transparent px-3 py-2.5 text-[15px] leading-6 outline-none placeholder:text-slate-400"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={kind === "ask" ? "Ask anything about your documents…" : "Type words or a topic to find in your documents…"}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSubmit();
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-1">
            <ModeTab active={kind === "ask"} onClick={() => setKind("ask")}>💬 Answer</ModeTab>
            <ModeTab active={kind === "find"} onClick={() => setKind("find")}>🔍 Find passages</ModeTab>
            <details className="relative text-xs text-slate-500">
              <summary className="cursor-pointer list-none rounded-full px-3 py-1.5 font-semibold hover:bg-mist hover:text-slate-700">⚙ Options</summary>
              <div className="absolute bottom-10 left-0 z-10 w-72 space-y-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-card">
                <label className="block">
                  <span className="font-semibold text-slate-700">How should I look for matches?</span>
                  <select className="select-control mt-1.5 w-full" value={mode} onChange={(event) => setMode(event.target.value as SearchMode)}>
                    {matchOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                  <span className="mt-1 block leading-5">{matchOptions.find((option) => option.value === mode)?.hint}</span>
                  {kind === "ask" && <span className="mt-1 block leading-5 text-slate-400">Answers always use “Best match”.</span>}
                </label>
                <label className="block">
                  <span className="font-semibold text-slate-700">How many passages should I read?</span>
                  <select className="select-control mt-1.5 w-full" value={topK} onChange={(event) => setTopK(Number(event.target.value))}>
                    <option value={3}>A few (3), faster</option>
                    <option value={5}>Some (5), recommended</option>
                    <option value={8}>More (8)</option>
                    <option value={10}>Lots (10), most thorough</option>
                  </select>
                  <span className="mt-1 block leading-5 text-slate-400">Summaries and small documents are always read in full.</span>
                </label>
              </div>
            </details>
          </div>
          <button
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-lg text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
            disabled={busy || tooShort}
            onClick={onSubmit}
            title={kind === "ask" ? "Send" : "Find"}
            aria-label="Send"
          >
            {busy ? <span className="h-3 w-3 rounded-sm bg-white" /> : "↑"}
          </button>
        </div>
      </div>
      <p className="mt-2 truncate px-4 text-center text-xs text-slate-400" title={scopeLabel}>
        Asking about <span className="font-medium text-slate-500">{scopeLabel}</span> · Answers come only from your documents. Check important details.
      </p>
    </div>
  );
}

function ModeTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${active ? "bg-teal/10 text-teal" : "text-slate-500 hover:bg-mist hover:text-slate-700"}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function Step({ number, children }: { number: number; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-teal/10 text-xs font-bold text-teal">{number}</span>
      <span className="leading-6">{children}</span>
    </li>
  );
}

export default App;
