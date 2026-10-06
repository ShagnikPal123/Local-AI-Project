"""The connectors catalogue: every app Nyx can connect to, and the owner's connections to them.

Owner, 2026-09-22 (Plan Null N10): "Update the connectors and make in the format of the photo and add as many as
possible, Gmail, mail, docs, sheets, excel, Microsoft apps, vercel, and more. Basically all the things Claude and
ChatGPT can use as their connectors." Update 1 (U9/U24) adds "Gmail adding here not keys and models", other AI apps,
finance apps, and "the user can input a site or connector, it either finds it or creates the connection".

Two halves:

* **The catalogue** is data only (AGENTS.md invariant 2): what each app is, which fields it needs, where the owner gets
  a token, and the real, documented API calls Nyx may make with it. An action is listed only when its endpoint is
  documented and stable; an app whose API Nyx cannot honestly drive yet has no actions rather than invented ones.
* **Connections** say which entries the owner connected. Plain values (a site name, a region) live in
  ``connectors/connections.json``; every secret goes to ``secret_store`` under ``connector:<id>:<field>`` and never
  leaves this process except as a request header (invariant 5). Google and Microsoft apps connect through their own
  sign-in (``google_oauth``, ``connectors/microsoft_graph``), AI model providers through the Keys & Models store, and
  the owner's own invented connectors through ``connector_builder``. ``connector_use`` reads all of them through here.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from paths import data_path

KINDS = ("rest", "mcp", "oauth_google", "oauth_microsoft", "builtin", "website", "webhook", "provider", "model")

#: Grid order. ``custom`` holds the "add any site / API / MCP server" starters.
CATEGORIES: List[Dict[str, str]] = [
    {"id": "google", "label": "Google"},
    {"id": "microsoft", "label": "Microsoft 365"},
    {"id": "ai", "label": "AI models & apps"},
    {"id": "developer", "label": "Developer"},
    {"id": "productivity", "label": "Productivity"},
    {"id": "communication", "label": "Messaging & email"},
    {"id": "finance", "label": "Finance"},
    {"id": "files", "label": "Files & cloud"},
    {"id": "media", "label": "Music, video & social"},
    {"id": "knowledge", "label": "Knowledge & data"},
    {"id": "automation", "label": "Automation"},
    {"id": "mcp", "label": "MCP servers"},
    {"id": "custom", "label": "Add your own"},
]

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Small builders so each entry reads as one short paragraph
# ---------------------------------------------------------------------------

def _secret(key: str = "token", label: str = "API token", help_url: str = "", placeholder: str = "",
            required: bool = True) -> Dict[str, Any]:
    return {"key": key, "label": label, "secret": True, "required": required, "help_url": help_url,
            "kind": "password", "placeholder": placeholder}


def _plain(key: str, label: str, placeholder: str = "", required: bool = True, kind: str = "text",
           help_url: str = "", **extra: Any) -> Dict[str, Any]:
    return {"key": key, "label": label, "secret": False, "required": required, "help_url": help_url,
            "kind": kind, "placeholder": placeholder, **extra}


def _a(action_id: str, method: str, path: str, description: str, params: Optional[Dict[str, str]] = None, *,
       write: bool = False, body: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"id": action_id, "method": method, "path": path, "description": description,
                            "params": dict(params or {})}
    if write or method != "GET":
        spec["write"] = bool(write)
    if body:
        spec["body"] = body
    if query:
        spec["query"] = query
    return spec


def _get(action_id: str, path: str, description: str, params: Optional[Dict[str, str]] = None, **kw: Any) -> Dict[str, Any]:
    return _a(action_id, "GET", path, description, params, **kw)


def _c(connector_id: str, name: str, category: str, kind: str, description: str, **spec: Any) -> Dict[str, Any]:
    actions = list(spec.pop("actions", []) or [])
    entry = {"id": connector_id, "name": name, "category": category, "kind": kind, "description": description,
             "keywords": list(spec.pop("keywords", []) or []), "base_url": spec.pop("base_url", ""),
             "auth": spec.pop("auth", {"type": "bearer"}), "fields": list(spec.pop("fields", []) or []),
             "can": list(spec.pop("can", []) or []), "actions": actions,
             "docs_url": spec.pop("docs_url", ""), "domains": list(spec.pop("domains", []) or []),
             "color": spec.pop("color", "#a594ff"), "mark": spec.pop("mark", name[:1].upper()),
             "popular": int(spec.pop("popular", 50))}
    entry["writes"] = bool(spec.pop("writes", any(a.get("write") for a in actions)))
    entry.update(spec)
    return entry


def _google(connector_id: str, name: str, product: str, api: str, base: str, description: str, *,
            can: List[str], actions: List[Dict[str, Any]], color: str, mark: str, keywords: List[str],
            docs_url: str, tools: Iterable[str] = (), popular: int = 80) -> Dict[str, Any]:
    """A Google Workspace app: one Google sign-in, the product's own scope, the product's own API."""
    return _c(connector_id, name, "google", "oauth_google", description, base_url=base, auth={"type": "oauth"},
              google_product=product, enable_url=f"https://console.cloud.google.com/apis/library/{api}",
              can=can, actions=actions, color=color, mark=mark, keywords=keywords, docs_url=docs_url,
              tools=list(tools), popular=popular, domains=[])


def _microsoft(connector_id: str, name: str, product: str, description: str, *, can: List[str],
               actions: List[Dict[str, Any]], color: str, mark: str, keywords: List[str], docs_url: str,
               popular: int = 75, note: str = "") -> Dict[str, Any]:
    """A Microsoft 365 app: one Microsoft sign-in (device code), the product's Graph permissions."""
    return _c(connector_id, name, "microsoft", "oauth_microsoft", description,
              base_url="https://graph.microsoft.com/v1.0", auth={"type": "oauth"}, microsoft_product=product,
              can=can, actions=actions, color=color, mark=mark, keywords=keywords, docs_url=docs_url,
              popular=popular, note=note)


def _provider(connector_id: str, name: str, provider: str, base: str, description: str, *, help_url: str,
              auth: Optional[Dict[str, Any]] = None, color: str, mark: str, keywords: List[str],
              actions: Optional[List[Dict[str, Any]]] = None, paid: bool = False, popular: int = 70) -> Dict[str, Any]:
    """An AI model provider Nyx already knows (Keys & Models): connecting it saves the same key Keys uses."""
    return _c(connector_id, name, "ai", "provider", description, provider=provider, base_url=base,
              auth=auth or {"type": "bearer", "token_field": "api_key"},
              fields=[_secret("api_key", "API key", help_url)], help_url=help_url, paid=paid,
              actions=actions if actions is not None else [_get("models", "/models", "The models this key can use")],
              can=["answer as one of Nyx's models", "list its models"], color=color, mark=mark,
              keywords=keywords + ["model", "ai", "llm"], popular=popular)


def _model(connector_id: str, name: str, company: str, chat_url: str, example: str, description: str, *,
           help_url: str, color: str, mark: str, keywords: List[str], models_path: str = "/models",
           popular: int = 55) -> Dict[str, Any]:
    """Another AI company with an OpenAI-compatible API: it joins the model menu like Keys → Add a model."""
    base = chat_url.rsplit("/chat/completions", 1)[0]
    return _c(connector_id, name, "ai", "model", description, company=company, chat_url=chat_url, base_url=base,
              auth={"type": "bearer", "token_field": "api_key"}, help_url=help_url,
              fields=[_plain("model", "Model", example), _secret("api_key", "API key", help_url)],
              actions=[_get("models", models_path, "The models this key can use")] if models_path else [],
              can=["answer as one of Nyx's models"], color=color, mark=mark,
              keywords=keywords + ["model", "ai", "llm"], popular=popular)


def _webhook(connector_id: str, name: str, description: str, *, domains: List[str], help_url: str, color: str,
             mark: str, keywords: List[str], placeholder: str) -> Dict[str, Any]:
    """Automation services that start a workflow when a JSON message arrives at the owner's hook address."""
    return _c(connector_id, name, "automation", "webhook", description, auth={"type": "none"},
              fields=[_secret("webhook_url", "Webhook address", help_url, placeholder)], domains=domains,
              actions=[_a("send", "POST", "", "Start the workflow with these fields as JSON",
                          {"anything": "any fields the workflow expects"}, write=True)],
              can=["start a workflow", "send it data"], color=color, mark=mark, keywords=keywords + ["workflow",
              "automation", "webhook", "trigger"], help_url=help_url)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

_GMAIL_TOOLS = ("email_list", "email_read", "email_send", "email_reply")

_ENTRIES: List[Dict[str, Any]] = [
    # --- Google Workspace: one sign-in with Google, each app asks for its own permission ---------------------
    _google("gmail", "Gmail", "gmail", "gmail.googleapis.com", "https://gmail.googleapis.com/gmail/v1",
            "Read, search, send and reply to your Gmail. Sign in with Google — or use an app password.",
            can=["search and read mail", "send and reply", "list labels"], color="#ea4335", mark="M",
            keywords=["email", "mail", "inbox", "gmail", "send an email", "unread"], tools=_GMAIL_TOOLS, popular=99,
            docs_url="https://developers.google.com/gmail/api/reference/rest",
            actions=[_get("profile", "/users/me/profile", "Which address is connected and how much mail it holds"),
                     _get("search", "/users/me/messages", "Find messages (returns ids; read one with message)",
                          {"q": "Gmail search words, e.g. from:anna is:unread", "maxResults": "how many (max 50)"}),
                     _get("message", "/users/me/messages/{id}", "Read one message",
                          {"id": "message id", "format": "metadata|full"}),
                     _get("labels", "/users/me/labels", "The mailbox's labels")]),
    _google("google_calendar", "Google Calendar", "calendar", "calendar-json.googleapis.com",
            "https://www.googleapis.com/calendar/v3", "See what's coming up and add or remove events.",
            can=["list upcoming events", "add an event", "remove an event"], color="#4285f4", mark="31",
            keywords=["calendar", "event", "meeting", "schedule", "appointment", "agenda"], popular=95,
            docs_url="https://developers.google.com/calendar/api/v3/reference",
            actions=[_get("calendars", "/users/me/calendarList", "The calendars on the account"),
                     _get("events", "/calendars/{calendar_id}/events", "Events in a calendar",
                          {"calendar_id": "primary, or a calendar id", "timeMin": "start, RFC 3339 (2026-10-04T00:00:00Z)",
                           "timeMax": "end, RFC 3339", "q": "words to match", "singleEvents": "true",
                           "orderBy": "startTime (needs singleEvents=true)", "maxResults": "how many"}),
                     _a("create_event", "POST", "/calendars/{calendar_id}/events", "Add an event",
                        {"calendar_id": "primary", "summary": "title", "description": "notes", "location": "where",
                         "start": '{"dateTime": "2026-10-05T15:00:00-04:00"}', "end": '{"dateTime": "…"}'}, write=True),
                     _a("delete_event", "DELETE", "/calendars/{calendar_id}/events/{event_id}", "Remove an event",
                        {"calendar_id": "primary", "event_id": "event id"}, write=True)]),
    _google("google_drive", "Google Drive", "drive", "drive.googleapis.com", "https://www.googleapis.com/drive/v3",
            "Find files in Drive and read Docs and Sheets as text.",
            can=["search files", "read a file's details", "read a Doc or Sheet as text"], color="#1fa463", mark="D",
            keywords=["drive", "file", "files", "folder", "document", "google drive"], popular=92,
            docs_url="https://developers.google.com/drive/api/reference/rest/v3",
            actions=[_get("search", "/files", "Find files",
                          {"q": "Drive query, e.g. name contains 'budget'", "pageSize": "how many",
                           "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}),
                     _get("file", "/files/{file_id}", "One file's details",
                          {"file_id": "file id", "fields": "id,name,mimeType,size,modifiedTime,webViewLink"}),
                     _get("export", "/files/{file_id}/export", "Read a Google Doc, Sheet or Slides file as text",
                          {"file_id": "file id", "mimeType": "text/plain (Docs, Slides) or text/csv (Sheets)"}),
                     _get("about", "/about", "Who is signed in and how much space is used",
                          {"fields": "user,storageQuota"})]),
    _google("google_docs", "Google Docs", "docs", "docs.googleapis.com", "https://docs.googleapis.com/v1",
            "Read, create and write Google Docs.",
            can=["read a document", "create a document", "insert or change text"], color="#4285f4", mark="≡",
            keywords=["docs", "google docs", "document", "write a doc", "essay"], popular=90,
            docs_url="https://developers.google.com/docs/api/reference/rest",
            actions=[_get("document", "/documents/{document_id}", "Read a document", {"document_id": "document id"}),
                     _a("create", "POST", "/documents", "Create an empty document", {"title": "title"}, write=True),
                     _a("batch_update", "POST", "/documents/{document_id}:batchUpdate", "Insert or change text",
                        {"document_id": "document id",
                         "requests": '[{"insertText": {"location": {"index": 1}, "text": "Hello"}}]'}, write=True)]),
    _google("google_sheets", "Google Sheets", "sheets", "sheets.googleapis.com", "https://sheets.googleapis.com/v4",
            "Read and write spreadsheet cells, add rows, make new sheets.",
            can=["read cells", "append rows", "update cells", "create a spreadsheet"], color="#0f9d58", mark="▦",
            keywords=["sheets", "spreadsheet", "google sheets", "table", "rows", "cells"], popular=90,
            docs_url="https://developers.google.com/sheets/api/reference/rest",
            actions=[_get("spreadsheet", "/spreadsheets/{spreadsheet_id}", "A spreadsheet's title and tabs",
                          {"spreadsheet_id": "spreadsheet id", "fields": "properties.title,sheets.properties"}),
                     _get("values", "/spreadsheets/{spreadsheet_id}/values/{range}", "Read cells",
                          {"spreadsheet_id": "spreadsheet id", "range": "A1 range, e.g. Sheet1!A1:D20"}),
                     _a("append", "POST", "/spreadsheets/{spreadsheet_id}/values/{range}:append", "Add rows at the end",
                        {"spreadsheet_id": "spreadsheet id", "range": "Sheet1!A1", "values": '[["2026-10-04", 12.5]]'},
                        write=True, query={"valueInputOption": "USER_ENTERED"}),
                     _a("update", "PUT", "/spreadsheets/{spreadsheet_id}/values/{range}", "Overwrite cells",
                        {"spreadsheet_id": "spreadsheet id", "range": "Sheet1!B2", "values": '[["new value"]]'},
                        write=True, query={"valueInputOption": "USER_ENTERED"}),
                     _a("create", "POST", "/spreadsheets", "Create a spreadsheet",
                        {"properties": '{"title": "My sheet"}'}, write=True)]),
    _google("google_slides", "Google Slides", "slides", "slides.googleapis.com", "https://slides.googleapis.com/v1",
            "Read presentations and start new ones.", can=["read a presentation", "create a presentation"],
            color="#f4b400", mark="▭", keywords=["slides", "presentation", "deck", "google slides"], popular=70,
            docs_url="https://developers.google.com/slides/api/reference/rest",
            actions=[_get("presentation", "/presentations/{presentation_id}", "Read a presentation",
                          {"presentation_id": "presentation id"}),
                     _a("create", "POST", "/presentations", "Create a presentation", {"title": "title"}, write=True)]),
    _google("google_tasks", "Google Tasks", "tasks", "tasks.googleapis.com", "https://tasks.googleapis.com/tasks/v1",
            "Your to-do lists from Gmail and Calendar.", can=["list tasks", "add a task"], color="#4285f4", mark="✓",
            keywords=["tasks", "todo", "to-do", "reminder", "google tasks"], popular=60,
            docs_url="https://developers.google.com/tasks/reference/rest",
            actions=[_get("lists", "/users/@me/lists", "Your task lists"),
                     _get("tasks", "/lists/{tasklist}/tasks", "Tasks in a list",
                          {"tasklist": "list id (@default is the main list)", "showCompleted": "true|false"}),
                     _a("add", "POST", "/lists/{tasklist}/tasks", "Add a task",
                        {"tasklist": "@default", "title": "what to do", "notes": "details", "due": "RFC 3339 date"},
                        write=True)]),

    # --- Microsoft 365 through Microsoft Graph -------------------------------------------------------------------
    _microsoft("outlook", "Outlook", "outlook", "Outlook mail and calendar: read, search and send mail, see and add events.",
               can=["read and search mail", "send mail", "see the calendar", "add an event"], color="#0078d4", mark="O",
               keywords=["outlook", "email", "mail", "hotmail", "calendar", "meeting", "office 365"], popular=88,
               docs_url="https://learn.microsoft.com/graph/api/resources/mail-api-overview",
               actions=[_get("me", "/me", "Who is signed in"),
                        _get("inbox", "/me/mailFolders/inbox/messages", "Recent mail in the inbox",
                             {"$top": "how many", "$select": "subject,from,receivedDateTime,bodyPreview",
                              "$search": '"words to find" (in double quotes)'}),
                        _get("message", "/me/messages/{message_id}", "Read one message", {"message_id": "message id"}),
                        _a("send_mail", "POST", "/me/sendMail", "Send an email",
                           {"message": '{"subject": "…", "body": {"contentType": "Text", "content": "…"}, '
                                       '"toRecipients": [{"emailAddress": {"address": "someone@example.com"}}]}'},
                           write=True),
                        _get("calendar", "/me/calendarView", "Events between two times",
                             {"startDateTime": "2026-10-04T00:00:00", "endDateTime": "2026-10-11T00:00:00"}),
                        _a("create_event", "POST", "/me/events", "Add an event",
                           {"subject": "title", "start": '{"dateTime": "2026-10-05T15:00:00", "timeZone": "UTC"}',
                            "end": '{"dateTime": "…", "timeZone": "UTC"}'}, write=True)]),
    _microsoft("excel", "Excel", "excel", "Excel workbooks in OneDrive: read sheets and ranges, write cells, add table rows.",
               can=["find workbooks", "read a sheet", "write cells", "add rows to a table"], color="#21a366", mark="X",
               keywords=["excel", "workbook", "spreadsheet", "xlsx", "microsoft excel"], popular=86,
               docs_url="https://learn.microsoft.com/graph/api/resources/excel",
               actions=[_get("find", "/me/drive/root/search(q='{q}')", "Find workbooks by name",
                             {"q": "words in the file name, e.g. budget"}),
                        _get("worksheets", "/me/drive/items/{item_id}/workbook/worksheets", "The sheets in a workbook",
                             {"item_id": "the workbook's file id"}),
                        _get("used_range", "/me/drive/items/{item_id}/workbook/worksheets/{sheet}/usedRange",
                             "Everything filled in on a sheet", {"item_id": "file id", "sheet": "sheet name"}),
                        _get("range", "/me/drive/items/{item_id}/workbook/worksheets/{sheet}/range(address='{address}')",
                             "Read a range", {"item_id": "file id", "sheet": "sheet name", "address": "A1:D20"}),
                        _a("write_range", "PATCH",
                           "/me/drive/items/{item_id}/workbook/worksheets/{sheet}/range(address='{address}')",
                           "Write cells", {"item_id": "file id", "sheet": "sheet name", "address": "B2:C2",
                                           "values": '[["a", 1]]'}, write=True),
                        _a("add_rows", "POST", "/me/drive/items/{item_id}/workbook/tables/{table}/rows",
                           "Add rows to a table", {"item_id": "file id", "table": "table name",
                                                   "values": '[["a", 1]]'}, write=True)]),
    _microsoft("word", "Word", "word", "Find Word documents in OneDrive and open them in Word for the web.",
               can=["find documents", "a document's details and link"], color="#2b7cd3", mark="W",
               keywords=["word", "docx", "document", "microsoft word"], popular=84,
               docs_url="https://learn.microsoft.com/graph/api/resources/driveitem",
               note="Microsoft Graph has no API for the text inside a Word file, so Nyx finds documents and opens them.",
               actions=[_get("find", "/me/drive/root/search(q='{q}')", "Find documents by name",
                             {"q": "words in the file name"}),
                        _get("item", "/me/drive/items/{item_id}", "A document's details and web link",
                             {"item_id": "file id"})]),
    _microsoft("onedrive", "OneDrive", "onedrive", "Files in OneDrive: recent, folders and search.",
               can=["recent files", "browse folders", "search files"], color="#0f78d4", mark="☁",
               keywords=["onedrive", "files", "file", "folder", "cloud storage"], popular=80,
               docs_url="https://learn.microsoft.com/graph/api/resources/onedrive",
               actions=[_get("recent", "/me/drive/recent", "Recently used files"),
                        _get("root", "/me/drive/root/children", "Files and folders at the top level"),
                        _get("children", "/me/drive/items/{item_id}/children", "What is inside a folder",
                             {"item_id": "folder id"}),
                        _get("search", "/me/drive/root/search(q='{q}')", "Search files", {"q": "words to find"}),
                        _get("item", "/me/drive/items/{item_id}", "One file's details", {"item_id": "file id"})]),
    _microsoft("teams", "Microsoft Teams", "teams", "Your teams, channels and chats; send a chat message.",
               can=["list teams and channels", "read chats", "send a chat message"], color="#6264a7", mark="T",
               keywords=["teams", "microsoft teams", "chat", "channel"], popular=78,
               docs_url="https://learn.microsoft.com/graph/api/resources/teams-api-overview",
               note="Teams needs a work or school account.",
               actions=[_get("teams", "/me/joinedTeams", "The teams you are in"),
                        _get("channels", "/teams/{team_id}/channels", "Channels in a team", {"team_id": "team id"}),
                        _get("chats", "/me/chats", "Your chats"),
                        _get("chat_messages", "/me/chats/{chat_id}/messages", "Messages in a chat",
                             {"chat_id": "chat id", "$top": "how many"}),
                        _a("send_chat", "POST", "/chats/{chat_id}/messages", "Send a chat message",
                           {"chat_id": "chat id", "body": '{"content": "Hello"}'}, write=True)]),
    _microsoft("onenote", "OneNote", "onenote", "Read your OneNote notebooks and pages.",
               can=["list notebooks", "list pages", "read a page"], color="#7719aa", mark="N",
               keywords=["onenote", "notebook", "notes"], popular=60,
               docs_url="https://learn.microsoft.com/graph/api/resources/onenote-api-overview",
               actions=[_get("notebooks", "/me/onenote/notebooks", "Your notebooks"),
                        _get("pages", "/me/onenote/pages", "Recent pages", {"$top": "how many"}),
                        _get("page", "/me/onenote/pages/{page_id}/content", "Read a page", {"page_id": "page id"})]),

    # --- AI models and apps --------------------------------------------------------------------------------------
    _provider("openai", "OpenAI", "openai", "https://api.openai.com/v1", "GPT models for chat, vision and pictures.",
              help_url="https://platform.openai.com/api-keys", color="#10a37f", mark="◎",
              keywords=["openai", "gpt", "chatgpt", "dall-e"], paid=True, popular=90),
    _provider("anthropic", "Anthropic Claude", "claude", "https://api.anthropic.com/v1", "Claude models for chat and vision.",
              help_url="https://console.anthropic.com/settings/keys", color="#d97757", mark="✳",
              auth={"type": "header", "header": "x-api-key", "token_field": "api_key",
                    "extra_headers": {"anthropic-version": "2023-06-01"}},
              keywords=["anthropic", "claude"], paid=True, popular=88),
    _provider("gemini", "Google Gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta",
              "Gemini models: fast chat, vision and long documents. Free key.",
              help_url="https://aistudio.google.com/apikey", color="#8e75ff", mark="✦",
              auth={"type": "query", "param": "key", "token_field": "api_key"},
              keywords=["gemini", "google ai", "bard"], popular=90),
    _provider("groq", "Groq", "groq", "https://api.groq.com/openai/v1", "Very fast Llama, Qwen and GPT-OSS chat. Free key.",
              help_url="https://console.groq.com/keys", color="#f55036", mark="G", keywords=["groq", "llama"], popular=75),
    _provider("nvidia", "NVIDIA NIM", "nvidia", "https://integrate.api.nvidia.com/v1",
              "Nemotron, Llama Vision, FLUX pictures and more. Free credits.",
              help_url="https://build.nvidia.com/models", color="#76b900", mark="◣",
              keywords=["nvidia", "nemotron", "nim", "flux"], popular=75),
    _provider("deepseek", "DeepSeek", "deepseek", "https://api.deepseek.com", "DeepSeek chat and reasoning models.",
              help_url="https://platform.deepseek.com/api_keys", color="#4d6bfe", mark="D", keywords=["deepseek"],
              paid=True, popular=55,
              actions=[_get("models", "/models", "The models this key can use"),
                       _get("balance", "/user/balance", "The account's remaining balance")]),
    _model("mistral", "Mistral", "mistral", "https://api.mistral.ai/v1/chat/completions", "mistral-small-latest",
           "Mistral's models, with a free experiment tier.", help_url="https://console.mistral.ai/api-keys",
           color="#fa520f", mark="M", keywords=["mistral", "codestral"], popular=60),
    _model("openrouter", "OpenRouter", "openrouter", "https://openrouter.ai/api/v1/chat/completions",
           "meta-llama/llama-3.3-70b-instruct:free", "One key for hundreds of models; ids ending in :free cost nothing.",
           help_url="https://openrouter.ai/keys", color="#7c7fff", mark="⇄", keywords=["openrouter"], popular=60),
    _model("perplexity", "Perplexity", "perplexity", "https://api.perplexity.ai/chat/completions", "sonar",
           "Sonar models that search the web and cite sources.", help_url="https://www.perplexity.ai/settings/api",
           color="#20b8cd", mark="✱", keywords=["perplexity", "sonar"], models_path="", popular=60),
    _model("xai", "xAI Grok", "xai", "https://api.x.ai/v1/chat/completions", "grok-3-mini", "Grok models from xAI.",
           help_url="https://console.x.ai/", color="#e5e5ea", mark="X", keywords=["grok", "xai"], popular=50),
    _model("together", "Together AI", "together", "https://api.together.xyz/v1/chat/completions",
           "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", "Open models; ids ending in -Free cost nothing.",
           help_url="https://api.together.ai/settings/api-keys", color="#0f6fff", mark="T", keywords=["together"], popular=40),
    _model("cerebras", "Cerebras", "cerebras", "https://api.cerebras.ai/v1/chat/completions", "llama-3.3-70b",
           "The fastest tokens per second, with a free daily allowance.", help_url="https://cloud.cerebras.ai/",
           color="#f15a29", mark="C", keywords=["cerebras"], popular=40),
    _c("huggingface", "Hugging Face", "ai", "rest", "Search models, datasets and Spaces on the Hub.",
       base_url="https://huggingface.co", fields=[_secret("token", "Access token (optional for public data)",
                                                          "https://huggingface.co/settings/tokens", required=False)],
       can=["search models", "search datasets", "search Spaces"], color="#ffd21e", mark="🤗",
       keywords=["hugging face", "huggingface", "model hub", "dataset", "transformers"], popular=70,
       domains=["huggingface.co"], docs_url="https://huggingface.co/docs/hub/api",
       actions=[_get("models", "/api/models", "Search models", {"search": "words", "limit": "how many"}),
                _get("datasets", "/api/datasets", "Search datasets", {"search": "words", "limit": "how many"}),
                _get("spaces", "/api/spaces", "Search Spaces", {"search": "words", "limit": "how many"}),
                _get("whoami", "/api/whoami-v2", "Who the token belongs to")]),
    _c("replicate", "Replicate", "ai", "rest", "Run open models in the cloud; see your account and past runs.",
       base_url="https://api.replicate.com/v1", fields=[_secret("token", "API token", "https://replicate.com/account/api-tokens")],
       can=["list models", "list past predictions"], color="#e5e5ea", mark="R", keywords=["replicate"], popular=45,
       domains=["replicate.com"], docs_url="https://replicate.com/docs/reference/http",
       actions=[_get("account", "/account", "The account the token belongs to"),
                _get("models", "/models", "Public models"), _get("predictions", "/predictions", "Your past runs")]),
    _c("stability", "Stability AI", "ai", "rest", "Stable Diffusion image models; account and credit balance.",
       base_url="https://api.stability.ai", fields=[_secret("token", "API key", "https://platform.stability.ai/account/keys")],
       can=["account details", "credit balance"], color="#b55ef5", mark="S", keywords=["stability", "stable diffusion"],
       popular=40, domains=["stability.ai"], docs_url="https://platform.stability.ai/docs/api-reference",
       actions=[_get("account", "/v1/user/account", "Your account"), _get("balance", "/v1/user/balance", "Credits left")]),
    _c("elevenlabs", "ElevenLabs", "ai", "rest", "Lifelike voices: list voices and models, check your plan.",
       base_url="https://api.elevenlabs.io", auth={"type": "header", "header": "xi-api-key"},
       fields=[_secret("token", "API key", "https://elevenlabs.io/app/settings/api-keys")],
       can=["list voices", "list voice models", "plan and usage"], color="#e5e5ea", mark="II",
       keywords=["elevenlabs", "voice", "text to speech", "tts"], popular=50, domains=["elevenlabs.io"],
       docs_url="https://elevenlabs.io/docs/api-reference",
       actions=[_get("voices", "/v1/voices", "Your voices"), _get("models", "/v1/models", "Voice models"),
                _get("user", "/v1/user", "Plan and characters used")]),

    # --- Developer -----------------------------------------------------------------------------------------------
    _c("github", "GitHub", "developer", "rest", "Repositories, issues and pull requests.",
       base_url="https://api.github.com", fields=[_secret("token", "Personal access token",
                                                          "https://github.com/settings/personal-access-tokens")],
       can=["search repositories", "read and open issues", "pull requests", "notifications"], color="#f5f5f7", mark="GH",
       keywords=["github", "repo", "repository", "issue", "pull request", "commit", "code"], popular=97,
       domains=["github.com"], docs_url="https://docs.github.com/rest",
       mcp_url="https://api.githubcopilot.com/mcp/",
       actions=[_get("me", "/user", "Who the token belongs to"),
                _get("my_repos", "/user/repos", "Your repositories",
                     {"sort": "updated|created|pushed", "per_page": "how many (max 100)"}),
                _get("search_repos", "/search/repositories", "Search repositories", {"q": "search words"}),
                _get("issues", "/repos/{owner}/{repo}/issues", "Issues in a repository",
                     {"owner": "account", "repo": "repository", "state": "open|closed|all"}),
                _get("pulls", "/repos/{owner}/{repo}/pulls", "Pull requests in a repository",
                     {"owner": "account", "repo": "repository", "state": "open|closed|all"}),
                _get("notifications", "/notifications", "Your unread notifications"),
                _a("create_issue", "POST", "/repos/{owner}/{repo}/issues", "Open an issue",
                   {"owner": "account", "repo": "repository", "title": "title", "body": "text"}, write=True)]),
    _c("gitlab", "GitLab", "developer", "rest", "Projects, issues and merge requests on GitLab.com.",
       base_url="https://gitlab.com/api/v4", fields=[_secret("token", "Personal access token",
                                                             "https://gitlab.com/-/user_settings/personal_access_tokens")],
       can=["your projects", "issues", "merge requests", "open an issue"], color="#fc6d26", mark="GL",
       keywords=["gitlab", "merge request", "repo", "pipeline"], popular=70, domains=["gitlab.com"],
       docs_url="https://docs.gitlab.com/api/rest/",
       actions=[_get("me", "/user", "Who the token belongs to"),
                _get("projects", "/projects", "Your projects", {"membership": "true", "search": "words"}),
                _get("issues", "/issues", "Issues for you", {"scope": "assigned_to_me|created_by_me|all", "state": "opened"}),
                _get("merge_requests", "/merge_requests", "Merge requests for you",
                     {"scope": "assigned_to_me|created_by_me|all", "state": "opened"}),
                _a("create_issue", "POST", "/projects/{project_id}/issues", "Open an issue",
                   {"project_id": "project id or group/project", "title": "title", "description": "text"}, write=True)]),
    _c("vercel", "Vercel", "developer", "rest", "Projects, deployments and domains on Vercel.",
       base_url="https://api.vercel.com", fields=[_secret("token", "Access token", "https://vercel.com/account/settings/tokens")],
       can=["list projects", "recent deployments", "a deployment's status", "domains"], color="#f5f5f7", mark="▲",
       keywords=["vercel", "deploy", "deployment", "hosting", "website", "next.js"], popular=85,
       domains=["vercel.com"], docs_url="https://vercel.com/docs/rest-api",
       actions=[_get("me", "/v2/user", "Who the token belongs to"),
                _get("projects", "/v9/projects", "Projects on the account", {"search": "words", "limit": "how many"}),
                _get("deployments", "/v6/deployments", "Recent deployments",
                     {"projectId": "only this project", "limit": "how many", "state": "READY|ERROR|BUILDING"}),
                _get("deployment", "/v13/deployments/{id}", "One deployment's status", {"id": "deployment id or URL"}),
                _get("domains", "/v5/domains", "Domains on the account")]),
    _c("netlify", "Netlify", "developer", "rest", "Sites and deploys on Netlify.",
       base_url="https://api.netlify.com/api/v1",
       fields=[_secret("token", "Personal access token", "https://app.netlify.com/user/applications#personal-access-tokens")],
       can=["list sites", "a site's deploys"], color="#32e6e2", mark="◆", keywords=["netlify", "deploy", "hosting"],
       popular=55, domains=["netlify.com"], docs_url="https://open-api.netlify.com/",
       actions=[_get("me", "/user", "Who the token belongs to"), _get("sites", "/sites", "Your sites"),
                _get("deploys", "/sites/{site_id}/deploys", "A site's deploys", {"site_id": "site id"})]),
    _c("linear", "Linear", "developer", "rest", "Issues, projects and teams in Linear.",
       base_url="https://api.linear.app", auth={"type": "header", "header": "Authorization"},
       fields=[_secret("token", "Personal API key", "https://linear.app/settings/account/security")],
       can=["issues assigned to you", "teams", "any GraphQL query"], color="#5e6ad2", mark="◐",
       keywords=["linear", "issue", "ticket", "sprint", "bug"], popular=70, domains=["linear.app"],
       docs_url="https://linear.app/developers/graphql",
       actions=[_a("my_issues", "POST", "/graphql", "Issues assigned to you", {},
                   body={"query": "{ viewer { assignedIssues(first: 20) { nodes { identifier title url "
                                  "state { name } } } } }"}),
                _a("teams", "POST", "/graphql", "Your teams", {}, body={"query": "{ teams { nodes { id key name } } }"}),
                _a("graphql", "POST", "/graphql", "Any Linear GraphQL query (mutations change things)",
                   {"query": "GraphQL text", "variables": "JSON object"}, write=True)]),
    _c("jira", "Jira", "developer", "rest", "Jira Cloud issues and projects.",
       base_url="https://{site}.atlassian.net", auth={"type": "basic", "username_field": "email", "password_field": "token"},
       fields=[_plain("site", "Site", "your-site (from your-site.atlassian.net)", kind="subdomain", suffix=".atlassian.net"),
               _plain("email", "Atlassian account email", "you@example.com", kind="email"),
               _secret("token", "API token", "https://id.atlassian.com/manage-profile/security/api-tokens")],
       can=["search issues with JQL", "read an issue", "list projects"], color="#2684ff", mark="J",
       keywords=["jira", "atlassian", "ticket", "issue", "sprint", "jql"], popular=72, domains=["atlassian.net"],
       docs_url="https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
       actions=[_get("me", "/rest/api/3/myself", "Who is signed in"),
                _get("search", "/rest/api/3/search/jql", "Search issues",
                     {"jql": "e.g. assignee = currentUser() AND resolution = Unresolved", "maxResults": "how many",
                      "fields": "summary,status,assignee"}),
                _get("issue", "/rest/api/3/issue/{issue_key}", "Read one issue", {"issue_key": "e.g. PROJ-12"}),
                _get("projects", "/rest/api/3/project/search", "Projects", {"query": "words"})]),
    _c("confluence", "Confluence", "developer", "rest", "Confluence Cloud spaces and pages.",
       base_url="https://{site}.atlassian.net/wiki", auth={"type": "basic", "username_field": "email", "password_field": "token"},
       fields=[_plain("site", "Site", "your-site (from your-site.atlassian.net)", kind="subdomain", suffix=".atlassian.net"),
               _plain("email", "Atlassian account email", "you@example.com", kind="email"),
               _secret("token", "API token", "https://id.atlassian.com/manage-profile/security/api-tokens")],
       can=["search pages", "list spaces", "read a page"], color="#1868db", mark="C",
       keywords=["confluence", "wiki", "atlassian", "page", "space"], popular=55, domains=[],
       docs_url="https://developer.atlassian.com/cloud/confluence/rest/v2/",
       actions=[_get("spaces", "/api/v2/spaces", "Spaces"),
                _get("pages", "/api/v2/pages", "Pages", {"title": "exact title", "limit": "how many"}),
                _get("page", "/api/v2/pages/{page_id}", "Read a page", {"page_id": "page id", "body-format": "storage"}),
                _get("search", "/rest/api/search", "Search with CQL", {"cql": 'e.g. text ~ "roadmap"'})]),
    _c("figma", "Figma", "developer", "rest", "Read Figma files and comments; leave a comment.",
       base_url="https://api.figma.com", auth={"type": "header", "header": "X-Figma-Token"},
       fields=[_secret("token", "Personal access token", "https://www.figma.com/developers/api#access-tokens")],
       can=["read a file", "read comments", "post a comment"], color="#a259ff", mark="F",
       keywords=["figma", "design", "mockup", "prototype"], popular=72, domains=["figma.com"],
       docs_url="https://www.figma.com/developers/api",
       actions=[_get("me", "/v1/me", "Who the token belongs to"),
                _get("file", "/v1/files/{file_key}", "Read a file (from its URL: figma.com/design/<file_key>/…)",
                     {"file_key": "file key", "depth": "1 or 2 keeps it small"}),
                _get("comments", "/v1/files/{file_key}/comments", "Comments on a file", {"file_key": "file key"}),
                _a("comment", "POST", "/v1/files/{file_key}/comments", "Post a comment",
                   {"file_key": "file key", "message": "text"}, write=True)]),

    # --- Productivity --------------------------------------------------------------------------------------------
    _c("notion", "Notion", "productivity", "rest", "Pages and databases in a Notion workspace.",
       base_url="https://api.notion.com/v1", auth={"type": "bearer", "extra_headers": {"Notion-Version": "2022-06-28"}},
       fields=[_secret("token", "Integration token", "https://www.notion.so/profile/integrations")],
       can=["search pages", "read a page", "add a page"], color="#f5f5f7", mark="N",
       keywords=["notion", "notes", "wiki", "page", "database"], popular=93, domains=["notion.so", "notion.com"],
       docs_url="https://developers.notion.com/reference",
       note="Share each page or database with your integration in Notion (••• → Connections), or it stays invisible.",
       actions=[_a("search", "POST", "/search", "Search pages and databases", {"query": "search words"}),
                _get("page", "/pages/{page_id}", "Read one page's properties", {"page_id": "page id"}),
                _get("blocks", "/blocks/{page_id}/children", "The text on a page", {"page_id": "page id"}),
                _a("create_page", "POST", "/pages", "Add a page",
                   {"parent": '{"page_id": "…"}', "properties": '{"title": {"title": [{"text": {"content": "Title"}}]}}',
                    "children": "optional blocks"}, write=True)]),
    _c("trello", "Trello", "productivity", "rest", "Boards, lists and cards.",
       base_url="https://api.trello.com/1", auth={"type": "query", "params": {"key": "api_key", "token": "token"}},
       fields=[_secret("api_key", "API key", "https://trello.com/power-ups/admin", "from your Power-Up's API key page"),
               _secret("token", "Token", "https://trello.com/power-ups/admin")],
       can=["your boards", "lists and cards", "add a card"], color="#0c66e4", mark="▥",
       keywords=["trello", "board", "card", "kanban"], popular=75, domains=["trello.com"],
       docs_url="https://developer.atlassian.com/cloud/trello/rest/",
       actions=[_get("boards", "/members/me/boards", "Your boards", {"fields": "name,url"}),
                _get("lists", "/boards/{board_id}/lists", "Lists on a board", {"board_id": "board id"}),
                _get("cards", "/lists/{list_id}/cards", "Cards in a list", {"list_id": "list id"}),
                _a("add_card", "POST", "/cards", "Add a card", {"idList": "list id", "name": "title", "desc": "details"},
                   write=True)]),
    _c("asana", "Asana", "productivity", "rest", "Workspaces, projects and tasks in Asana.",
       base_url="https://app.asana.com/api/1.0", fields=[_secret("token", "Personal access token",
                                                                 "https://app.asana.com/0/my-apps")],
       can=["your workspaces", "projects", "your tasks"], color="#f06a6a", mark="◉",
       keywords=["asana", "task", "project", "todo"], popular=70, domains=["asana.com"],
       docs_url="https://developers.asana.com/reference/rest-api-reference",
       actions=[_get("me", "/users/me", "Who the token belongs to"), _get("workspaces", "/workspaces", "Your workspaces"),
                _get("projects", "/projects", "Projects in a workspace", {"workspace": "workspace id"}),
                _get("my_tasks", "/tasks", "Tasks assigned to you",
                     {"assignee": "me", "workspace": "workspace id", "completed_since": "now (only open tasks)"})]),
    _c("todoist", "Todoist", "productivity", "rest", "Your Todoist tasks and projects.",
       base_url="https://api.todoist.com/api/v1", fields=[_secret("token", "API token",
                                                                 "https://app.todoist.com/app/settings/integrations/developer")],
       can=["list tasks", "list projects", "add a task", "close a task"], color="#e44332", mark="✓",
       keywords=["todoist", "todo", "to-do", "task", "reminder"], popular=60, domains=["todoist.com"],
       docs_url="https://developer.todoist.com/api/v1/",
       actions=[_get("tasks", "/tasks", "Open tasks", {"project_id": "only this project"}),
                _get("projects", "/projects", "Projects"),
                _a("add", "POST", "/tasks", "Add a task",
                   {"content": "what to do", "due_string": "e.g. tomorrow at 5pm", "priority": "1-4"}, write=True),
                _a("close", "POST", "/tasks/{task_id}/close", "Mark a task done", {"task_id": "task id"}, write=True)]),
    _c("clickup", "ClickUp", "productivity", "rest", "Workspaces, lists and tasks in ClickUp.",
       base_url="https://api.clickup.com/api/v2", auth={"type": "header", "header": "Authorization"},
       fields=[_secret("token", "Personal API token", "https://app.clickup.com/settings/apps")],
       can=["workspaces", "tasks in a list", "add a task"], color="#7b68ee", mark="⌃",
       keywords=["clickup", "task", "project"], popular=50, domains=["clickup.com"],
       docs_url="https://developer.clickup.com/reference",
       actions=[_get("workspaces", "/team", "Your workspaces"),
                _get("tasks", "/list/{list_id}/task", "Tasks in a list", {"list_id": "list id"}),
                _a("add_task", "POST", "/list/{list_id}/task", "Add a task",
                   {"list_id": "list id", "name": "title", "description": "details"}, write=True)]),
    _c("monday", "monday.com", "productivity", "rest", "Boards and items on monday.com.",
       base_url="https://api.monday.com", auth={"type": "header", "header": "Authorization"},
       fields=[_secret("token", "API token", "https://support.monday.com/hc/en-us/articles/360005144659")],
       can=["your boards", "any GraphQL query"], color="#ff3d57", mark="m",
       keywords=["monday", "monday.com", "board", "item"], popular=45, domains=["monday.com"],
       docs_url="https://developer.monday.com/api-reference/",
       actions=[_a("boards", "POST", "/v2", "Your boards", {}, body={"query": "{ boards (limit: 20) { id name } }"}),
                _a("graphql", "POST", "/v2", "Any monday GraphQL query (mutations change things)",
                   {"query": "GraphQL text", "variables": "JSON object"}, write=True)]),
    _c("airtable", "Airtable", "productivity", "rest", "Bases, tables and records.",
       base_url="https://api.airtable.com/v0", fields=[_secret("token", "Personal access token",
                                                               "https://airtable.com/create/tokens")],
       can=["your bases", "read records", "add records"], color="#fcb400", mark="◇",
       keywords=["airtable", "base", "table", "records", "database"], popular=65, domains=["airtable.com"],
       docs_url="https://airtable.com/developers/web/api/introduction",
       actions=[_get("bases", "/meta/bases", "Your bases"),
                _get("tables", "/meta/bases/{base_id}/tables", "Tables in a base", {"base_id": "base id (app…)"}),
                _get("records", "/{base_id}/{table}", "Records in a table",
                     {"base_id": "base id", "table": "table name or id", "maxRecords": "how many",
                      "filterByFormula": "optional formula"}),
                _a("add_records", "POST", "/{base_id}/{table}", "Add records",
                   {"base_id": "base id", "table": "table name", "records": '[{"fields": {"Name": "…"}}]'}, write=True)]),
    _c("hubspot", "HubSpot", "productivity", "rest", "Contacts, companies and deals in HubSpot CRM.",
       base_url="https://api.hubapi.com", fields=[_secret("token", "Private app access token",
                                                          "https://developers.hubspot.com/docs/api/private-apps")],
       can=["contacts", "companies", "deals"], color="#ff7a59", mark="H",
       keywords=["hubspot", "crm", "contact", "deal", "lead"], popular=50, domains=["hubspot.com"],
       docs_url="https://developers.hubspot.com/docs/api/crm/understanding-the-crm",
       actions=[_get("contacts", "/crm/v3/objects/contacts", "Contacts", {"limit": "how many"}),
                _get("companies", "/crm/v3/objects/companies", "Companies", {"limit": "how many"}),
                _get("deals", "/crm/v3/objects/deals", "Deals", {"limit": "how many"})]),
    _c("mailchimp", "Mailchimp", "productivity", "rest", "Audiences and campaigns in Mailchimp.",
       base_url="https://{dc}.api.mailchimp.com/3.0", auth={"type": "basic", "username": "nyx", "password_field": "token"},
       fields=[_secret("token", "API key", "https://us1.admin.mailchimp.com/account/api/"),
               _plain("dc", "Server prefix", "the part after the dash in your key, e.g. us21")],
       can=["audiences", "campaigns"], color="#ffe01b", mark="✉",
       keywords=["mailchimp", "newsletter", "campaign", "audience"], popular=40, domains=["mailchimp.com"],
       docs_url="https://mailchimp.com/developer/marketing/api/",
       actions=[_get("audiences", "/lists", "Your audiences"), _get("campaigns", "/campaigns", "Your campaigns",
                                                                      {"count": "how many"})]),
    _c("obsidian", "Obsidian", "productivity", "builtin", "Your Obsidian vault through the Local REST API plugin.",
       registry="obsidian", auth={"type": "none"}, can=["search notes", "read and write notes"], color="#a882ff", mark="◆",
       keywords=["obsidian", "vault", "notes", "markdown"], popular=60, docs_url="https://obsidian.md/",
       note="Install the Local REST API community plugin in Obsidian; Nyx finds it on this PC."),

    # --- Messaging and email --------------------------------------------------------------------------------------
    _c("email", "Email (any provider)", "communication", "builtin",
       "Any mailbox with IMAP and SMTP — Outlook.com, iCloud, Yahoo and others — using an app password.",
       registry="email", auth={"type": "none"}, tools=list(_GMAIL_TOOLS), can=["read mail", "send and reply"],
       color="#64d2ff", mark="@", keywords=["email", "mail", "inbox", "imap", "icloud", "yahoo", "send an email"],
       popular=80),
    _c("slack", "Slack", "communication", "rest", "Channels and messages in a Slack workspace.",
       base_url="https://slack.com/api", fields=[_secret("token", "Bot token (xoxb-…)", "https://api.slack.com/apps")],
       can=["list channels", "read a channel", "post a message"], color="#e01e5a", mark="#",
       keywords=["slack", "channel", "message", "workspace", "dm"], popular=92, domains=["slack.com"],
       docs_url="https://api.slack.com/methods",
       actions=[_get("channels", "/conversations.list", "Channels in the workspace", {"limit": "how many"}),
                _get("history", "/conversations.history", "Recent messages in a channel",
                     {"channel": "channel id", "limit": "how many"}),
                _a("post", "POST", "/chat.postMessage", "Post a message",
                   {"channel": "channel id", "text": "what to say"}, write=True)]),
    _c("discord", "Discord", "communication", "rest", "Your bot's servers and channels; read and post messages.",
       base_url="https://discord.com/api/v10", auth={"type": "header", "header": "Authorization", "prefix": "Bot "},
       fields=[_secret("token", "Bot token", "https://discord.com/developers/applications")],
       can=["the bot's servers", "read a channel", "post a message"], color="#5865f2", mark="D",
       keywords=["discord", "server", "channel", "guild"], popular=70, domains=["discord.com"],
       docs_url="https://discord.com/developers/docs/reference",
       actions=[_get("me", "/users/@me", "The bot's account"), _get("servers", "/users/@me/guilds", "Servers the bot is in"),
                _get("channels", "/guilds/{guild_id}/channels", "Channels in a server", {"guild_id": "server id"}),
                _get("messages", "/channels/{channel_id}/messages", "Recent messages",
                     {"channel_id": "channel id", "limit": "how many (max 100)"}),
                _a("post", "POST", "/channels/{channel_id}/messages", "Post a message",
                   {"channel_id": "channel id", "content": "what to say"}, write=True)]),
    _c("telegram", "Telegram", "communication", "rest", "A Telegram bot: read what people sent it and reply.",
       base_url="https://api.telegram.org/bot{token}", auth={"type": "none"},
       fields=[_secret("token", "Bot token from @BotFather", "https://core.telegram.org/bots#how-do-i-create-a-bot")],
       can=["read messages sent to the bot", "send a message"], color="#26a5e4", mark="✈",
       keywords=["telegram", "bot", "message"], popular=55, domains=["telegram.org"],
       docs_url="https://core.telegram.org/bots/api",
       actions=[_get("me", "/getMe", "The bot's account"),
                _get("updates", "/getUpdates", "Messages sent to the bot", {"limit": "how many", "offset": "after this id"}),
                _a("send", "POST", "/sendMessage", "Send a message", {"chat_id": "chat id", "text": "what to say"},
                   write=True)]),

    # --- Finance -------------------------------------------------------------------------------------------------
    _c("yahoo_finance", "Yahoo Finance (quotes)", "finance", "builtin",
       "Live stock quotes, history and market hours from public feeds. No key.", registry="finance",
       auth={"type": "none"}, can=["stock quotes", "price history", "is the market open"], color="#7e1fff", mark="Y!",
       keywords=["stock", "quote", "price", "market", "ticker", "shares", "nasdaq", "s&p"], popular=85),
    _c("alpaca", "Alpaca", "finance", "rest", "Your Alpaca brokerage account: balance, positions and orders (read only).",
       base_url="https://{environment}.alpaca.markets/v2",
       auth={"type": "headers", "headers": {"APCA-API-KEY-ID": "key_id", "APCA-API-SECRET-KEY": "secret_key"}},
       fields=[_plain("environment", "Account", "paper-api (practice) or api (real money)", kind="choice",
                      choices=["paper-api", "api"], default="paper-api"),
               _plain("key_id", "API key ID", "PK…", help_url="https://app.alpaca.markets/paper/dashboard/overview"),
               _secret("secret_key", "Secret key", "https://app.alpaca.markets/paper/dashboard/overview")],
       can=["account balance", "open positions", "orders"], color="#fcd535", mark="A",
       keywords=["alpaca", "broker", "brokerage", "positions", "portfolio", "trading"], popular=60,
       domains=["alpaca.markets"], docs_url="https://docs.alpaca.markets/reference",
       note="Read only: Nyx's Trading tab places orders, never this connector.",
       actions=[_get("account", "/account", "Balance and buying power"), _get("positions", "/positions", "Open positions"),
                _get("orders", "/orders", "Orders", {"status": "open|closed|all", "limit": "how many"})]),
    _c("polygon", "Polygon.io (Massive)", "finance", "rest", "Stock, options, forex and crypto market data.",
       base_url="https://api.polygon.io", auth={"type": "query", "param": "apiKey"},
       fields=[_secret("token", "API key", "https://polygon.io/dashboard/keys")],
       can=["previous day's prices", "daily bars", "find tickers"], color="#8c7cff", mark="P",
       keywords=["polygon", "massive", "market data", "stock", "options", "bars"], popular=55,
       domains=["polygon.io", "massive.com"], docs_url="https://polygon.io/docs",
       actions=[_get("previous", "/v2/aggs/ticker/{ticker}/prev", "The previous trading day", {"ticker": "e.g. AAPL"}),
                _get("bars", "/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}", "Daily bars between two dates",
                     {"ticker": "e.g. AAPL", "from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}),
                _get("tickers", "/v3/reference/tickers", "Find tickers", {"search": "words", "limit": "how many"})]),
    _c("alpha_vantage", "Alpha Vantage", "finance", "rest", "Stock quotes, daily prices and symbol search.",
       base_url="https://www.alphavantage.co", auth={"type": "query", "param": "apikey"},
       fields=[_secret("token", "API key", "https://www.alphavantage.co/support/#api-key")],
       can=["a stock quote", "daily prices", "symbol search"], color="#1aa7ec", mark="α",
       keywords=["alpha vantage", "stock", "quote", "forex"], popular=50, domains=["alphavantage.co"],
       docs_url="https://www.alphavantage.co/documentation/",
       actions=[_get("quote", "/query", "Latest quote", {"symbol": "e.g. IBM"}, query={"function": "GLOBAL_QUOTE"}),
                _get("daily", "/query", "Daily prices", {"symbol": "e.g. IBM", "outputsize": "compact"},
                     query={"function": "TIME_SERIES_DAILY"}),
                _get("search", "/query", "Find a symbol", {"keywords": "company name"}, query={"function": "SYMBOL_SEARCH"})]),
    _c("finnhub", "Finnhub", "finance", "rest", "Real-time quotes, company news and symbol search.",
       base_url="https://finnhub.io/api/v1", auth={"type": "query", "param": "token"},
       fields=[_secret("token", "API key", "https://finnhub.io/dashboard")],
       can=["a quote", "company news", "symbol search"], color="#1db954", mark="F",
       keywords=["finnhub", "stock", "quote", "news", "earnings"], popular=50, domains=["finnhub.io"],
       docs_url="https://finnhub.io/docs/api",
       actions=[_get("quote", "/quote", "Latest quote", {"symbol": "e.g. AAPL"}),
                _get("news", "/company-news", "Company news", {"symbol": "AAPL", "from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}),
                _get("search", "/search", "Find a symbol", {"q": "company name"})]),
    _c("fred", "FRED (Federal Reserve)", "finance", "rest", "US economic data: rates, inflation, jobs and more.",
       base_url="https://api.stlouisfed.org/fred", auth={"type": "query", "param": "api_key"},
       fields=[_secret("token", "API key", "https://fredaccount.stlouisfed.org/apikeys")],
       can=["a data series", "search series"], color="#4a90d9", mark="F",
       keywords=["fred", "economy", "inflation", "interest rate", "gdp", "unemployment", "cpi"], popular=40,
       domains=["stlouisfed.org"], docs_url="https://fred.stlouisfed.org/docs/api/fred/",
       actions=[_get("observations", "/series/observations", "Values of a series",
                     {"series_id": "e.g. CPIAUCSL, UNRATE, DFF", "observation_start": "YYYY-MM-DD"},
                     query={"file_type": "json"}),
                _get("search", "/series/search", "Find series", {"search_text": "words"}, query={"file_type": "json"})]),
    _c("coinbase", "Coinbase (prices)", "finance", "rest", "Live crypto prices and exchange rates. No key.",
       base_url="https://api.coinbase.com/v2", auth={"type": "none"},
       can=["spot price of a coin", "exchange rates"], color="#0052ff", mark="◯",
       keywords=["coinbase", "crypto", "bitcoin", "ethereum", "btc", "eth"], popular=55, domains=["coinbase.com"],
       docs_url="https://docs.cdp.coinbase.com/coinbase-app/track-apis/prices",
       note="Prices only. Reading or trading in a Coinbase account needs signed keys Nyx does not handle.",
       actions=[_get("spot", "/prices/{pair}/spot", "Spot price", {"pair": "e.g. BTC-USD"}),
                _get("rates", "/exchange-rates", "Exchange rates", {"currency": "e.g. USD"})]),
    _c("coingecko", "CoinGecko", "finance", "rest", "Prices and market data for thousands of coins. No key.",
       base_url="https://api.coingecko.com/api/v3", auth={"type": "none"},
       can=["coin prices", "trending coins", "find a coin"], color="#8dc63f", mark="🦎",
       keywords=["coingecko", "crypto", "coin", "token price"], popular=45, domains=["coingecko.com"],
       docs_url="https://docs.coingecko.com/reference/introduction",
       actions=[_get("price", "/simple/price", "Prices", {"ids": "e.g. bitcoin,ethereum", "vs_currencies": "usd"}),
                _get("trending", "/search/trending", "Trending coins"), _get("search", "/search", "Find a coin", {"query": "name"})]),
    _c("stripe", "Stripe", "finance", "rest", "Balance, payments, customers and invoices (read only).",
       base_url="https://api.stripe.com/v1", fields=[_secret("token", "Restricted key (read only is enough)",
                                                             "https://dashboard.stripe.com/apikeys")],
       can=["balance", "recent payments", "customers", "invoices"], color="#635bff", mark="S",
       keywords=["stripe", "payment", "payments", "invoice", "customer", "revenue", "charge"], popular=75,
       domains=["stripe.com"], docs_url="https://docs.stripe.com/api", mcp_url="https://mcp.stripe.com",
       actions=[_get("balance", "/balance", "Your balance"),
                _get("payments", "/payment_intents", "Recent payments", {"limit": "how many"}),
                _get("customers", "/customers", "Customers", {"limit": "how many", "email": "only this email"}),
                _get("invoices", "/invoices", "Invoices", {"limit": "how many", "status": "draft|open|paid"})]),
    _c("plaid", "Plaid (sandbox)", "finance", "rest", "Try Plaid's bank data API with its sandbox keys — no real accounts.",
       base_url="https://sandbox.plaid.com",
       auth={"type": "headers", "headers": {"PLAID-CLIENT-ID": "client_id", "PLAID-SECRET": "secret"}},
       fields=[_plain("client_id", "Client ID", "", help_url="https://dashboard.plaid.com/developers/keys"),
               _secret("secret", "Sandbox secret", "https://dashboard.plaid.com/developers/keys")],
       can=["search banks", "list banks"], color="#e5e5ea", mark="▣", keywords=["plaid", "bank", "banking"],
       popular=30, domains=["plaid.com"], docs_url="https://plaid.com/docs/api/",
       actions=[_a("institutions", "POST", "/institutions/get", "List banks",
                   {"count": "how many", "offset": "0", "country_codes": '["US"]'}),
                _a("search", "POST", "/institutions/search", "Find a bank",
                   {"query": "bank name", "products": '["transactions"]', "country_codes": '["US"]'})]),

    # --- Files and cloud ------------------------------------------------------------------------------------------
    _c("dropbox", "Dropbox", "files", "rest", "Browse and search your Dropbox.",
       base_url="https://api.dropboxapi.com/2", fields=[_secret("token", "Access token", "https://www.dropbox.com/developers/apps")],
       can=["list a folder", "search files", "account details"], color="#0061ff", mark="◈",
       keywords=["dropbox", "files", "folder", "cloud storage"], popular=65, domains=["dropbox.com"],
       docs_url="https://www.dropbox.com/developers/documentation/http/documentation",
       actions=[_a("account", "POST", "/users/get_current_account", "Who the token belongs to"),
                _a("list_folder", "POST", "/files/list_folder", "What is in a folder", {"path": '"" for the top, or /Folder'}),
                _a("search", "POST", "/files/search_v2", "Search files", {"query": "words"})]),
    _c("aws_s3", "Amazon S3", "files", "rest", "List buckets and files in Amazon S3 (read only).",
       base_url="https://s3.{region}.amazonaws.com", auth={"type": "aws_sigv4", "service": "s3"},
       fields=[_plain("region", "Region", "us-east-1"),
               _plain("access_key_id", "Access key ID", "AKIA…", help_url="https://console.aws.amazon.com/iam/home#/security_credentials"),
               _secret("secret_access_key", "Secret access key", "https://console.aws.amazon.com/iam/home#/security_credentials")],
       can=["list buckets", "list files in a bucket"], color="#ff9900", mark="S3",
       keywords=["s3", "aws", "amazon s3", "bucket", "storage"], popular=55, domains=["amazonaws.com"],
       docs_url="https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html",
       actions=[_get("buckets", "/", "Your buckets"),
                _get("files", "/{bucket}", "Files in a bucket", {"bucket": "bucket name", "prefix": "only under this folder"},
                     query={"list-type": "2"})]),
    _c("cloudflare", "Cloudflare", "files", "rest", "Accounts, zones (domains) and token checks on Cloudflare.",
       base_url="https://api.cloudflare.com/client/v4", fields=[_secret("token", "API token",
                                                                       "https://dash.cloudflare.com/profile/api-tokens")],
       can=["check the token", "list zones", "list accounts"], color="#f38020", mark="☁",
       keywords=["cloudflare", "dns", "domain", "zone", "cdn"], popular=55, domains=["cloudflare.com"],
       docs_url="https://developers.cloudflare.com/api/",
       actions=[_get("verify", "/user/tokens/verify", "Is the token valid"), _get("zones", "/zones", "Your domains"),
                _get("accounts", "/accounts", "Your accounts")]),
    _c("supabase", "Supabase", "files", "rest", "Your Supabase projects (Management API).",
       base_url="https://api.supabase.com", fields=[_secret("token", "Personal access token",
                                                            "https://supabase.com/dashboard/account/tokens")],
       can=["list projects"], color="#3ecf8e", mark="⚡", keywords=["supabase", "postgres", "database"], popular=55,
       domains=["supabase.com"], docs_url="https://supabase.com/docs/reference/api/introduction",
       actions=[_get("projects", "/v1/projects", "Your projects")]),
    _c("supabase_db", "Supabase database", "files", "rest", "Read and add rows in a Supabase project's tables.",
       base_url="https://{project_ref}.supabase.co/rest/v1",
       auth={"type": "headers", "headers": {"apikey": "token", "Authorization": "token"}, "prefixes": {"Authorization": "Bearer "}},
       fields=[_plain("project_ref", "Project ref", "the id in your-ref.supabase.co", kind="subdomain", suffix=".supabase.co"),
               _secret("token", "API key (anon or service role)", "https://supabase.com/dashboard/project/_/settings/api-keys")],
       can=["read rows", "add rows"], color="#3ecf8e", mark="DB", keywords=["supabase", "postgres", "table", "rows", "sql"],
       popular=45, domains=["supabase.co"], docs_url="https://supabase.com/docs/guides/api",
       actions=[_get("rows", "/{table}", "Rows in a table", {"table": "table name", "select": "*", "limit": "how many"}),
                _a("insert", "POST", "/{table}", "Add a row (send the columns as fields)",
                   {"table": "table name", "column": "value…"}, write=True)]),
    _c("firebase", "Firebase Realtime Database", "files", "rest", "Read and write paths in a Firebase Realtime Database.",
       base_url="https://{database}.firebaseio.com", auth={"type": "query", "param": "auth"},
       fields=[_plain("database", "Database name", "your-project-default-rtdb", kind="subdomain", suffix=".firebaseio.com"),
               _secret("token", "Database secret or ID token",
                       "https://console.firebase.google.com/project/_/settings/serviceaccounts/databasesecrets",
                       required=False)],
       can=["read a path", "write a path"], color="#ffca28", mark="🔥", keywords=["firebase", "realtime database"],
       popular=35, docs_url="https://firebase.google.com/docs/reference/rest/database",
       note="Call it with a path ending in .json, e.g. /users.json."),

    # --- Music, video and social ----------------------------------------------------------------------------------
    _c("youtube", "YouTube", "media", "rest", "Search YouTube and read video details.",
       base_url="https://www.googleapis.com/youtube/v3", auth={"type": "query", "param": "key"},
       fields=[_secret("token", "YouTube Data API key", "https://console.cloud.google.com/apis/credentials")],
       can=["search videos", "video details and stats"], color="#ff0000", mark="▶",
       keywords=["youtube", "video", "videos", "channel"], popular=85, domains=["youtube.com"],
       docs_url="https://developers.google.com/youtube/v3/docs",
       actions=[_get("search", "/search", "Search videos", {"q": "words", "maxResults": "how many"},
                     query={"part": "snippet", "type": "video"}),
                _get("videos", "/videos", "Details and stats for videos", {"id": "video id(s), comma separated"},
                     query={"part": "snippet,statistics"})]),
    _c("spotify", "Spotify", "media", "rest", "Search Spotify's catalogue for songs, artists and albums.",
       base_url="https://api.spotify.com/v1",
       auth={"type": "client_credentials", "token_url": "https://accounts.spotify.com/api/token"},
       fields=[_plain("client_id", "Client ID", "", help_url="https://developer.spotify.com/dashboard"),
               _secret("client_secret", "Client secret", "https://developer.spotify.com/dashboard")],
       can=["search songs, artists and albums", "an artist's top tracks"], color="#1ed760", mark="♫",
       keywords=["spotify", "music", "song", "artist", "album", "playlist"], popular=80, domains=["spotify.com"],
       docs_url="https://developer.spotify.com/documentation/web-api",
       note="Catalogue search only: playing music or reading your library needs a Spotify sign-in Nyx doesn't do yet.",
       actions=[_get("search", "/search", "Search the catalogue",
                     {"q": "words", "type": "track,artist,album", "limit": "how many"}),
                _get("top_tracks", "/artists/{artist_id}/top-tracks", "An artist's top tracks",
                     {"artist_id": "artist id", "market": "US"})]),
    _c("reddit", "Reddit", "media", "rest", "Read subreddits and search Reddit.",
       base_url="https://oauth.reddit.com",
       auth={"type": "client_credentials", "token_url": "https://www.reddit.com/api/v1/access_token"},
       fields=[_plain("client_id", "App ID", "", help_url="https://www.reddit.com/prefs/apps"),
               _secret("client_secret", "App secret", "https://www.reddit.com/prefs/apps")],
       can=["a subreddit's posts", "search posts"], color="#ff4500", mark="r/",
       keywords=["reddit", "subreddit", "post", "thread"], popular=60, domains=["reddit.com"],
       docs_url="https://www.reddit.com/dev/api/",
       actions=[_get("hot", "/r/{subreddit}/hot", "Hot posts in a subreddit", {"subreddit": "name", "limit": "how many"}),
                _get("search", "/search", "Search posts", {"q": "words", "limit": "how many", "sort": "relevance|new|top"})]),

    # --- Knowledge and data ---------------------------------------------------------------------------------------
    _c("wikipedia", "Wikipedia", "knowledge", "rest", "Search Wikipedia and read article summaries. No key.",
       base_url="https://en.wikipedia.org", auth={"type": "none"},
       can=["search articles", "an article's summary"], color="#e5e5ea", mark="W",
       keywords=["wikipedia", "wiki", "encyclopedia", "who was", "what is"], popular=80, domains=["wikipedia.org"],
       docs_url="https://www.mediawiki.org/wiki/API:Main_page",
       actions=[_get("search", "/w/api.php", "Search articles", {"srsearch": "words", "srlimit": "how many"},
                     query={"action": "query", "list": "search", "format": "json"}),
                _get("summary", "/api/rest_v1/page/summary/{title}", "An article's summary",
                     {"title": "article title, e.g. Alan_Turing"})]),
    _c("arxiv", "arXiv", "knowledge", "rest", "Search research papers on arXiv. No key.",
       base_url="https://export.arxiv.org", auth={"type": "none"}, can=["search papers"], color="#b31b1b", mark="χ",
       keywords=["arxiv", "paper", "papers", "research", "preprint"], popular=65, domains=["arxiv.org"],
       docs_url="https://info.arxiv.org/help/api/user-manual.html",
       actions=[_get("search", "/api/query", "Search papers (Atom XML)",
                     {"search_query": "e.g. all:transformers AND cat:cs.CL", "max_results": "how many",
                      "sortBy": "relevance|submittedDate"})]),
    _c("semantic_scholar", "Semantic Scholar", "knowledge", "rest", "Search papers with citation counts. No key.",
       base_url="https://api.semanticscholar.org/graph/v1", auth={"type": "none"},
       can=["search papers", "a paper's details"], color="#1857b6", mark="S2",
       keywords=["semantic scholar", "paper", "citation", "research"], popular=50, domains=["semanticscholar.org"],
       docs_url="https://api.semanticscholar.org/api-docs/",
       actions=[_get("search", "/paper/search", "Search papers",
                     {"query": "words", "limit": "how many", "fields": "title,year,citationCount,url,abstract"}),
                _get("paper", "/paper/{paper_id}", "One paper", {"paper_id": "id, DOI:… or arXiv:…",
                                                                 "fields": "title,year,authors,abstract,url"})]),
    _c("openweather", "OpenWeather", "knowledge", "rest", "Current weather and five-day forecasts.",
       base_url="https://api.openweathermap.org/data/2.5", auth={"type": "query", "param": "appid"},
       fields=[_secret("api_key", "API key", "https://home.openweathermap.org/api_keys")],
       can=["current weather for a place", "five-day forecast"], color="#eb6e4b", mark="☀",
       keywords=["weather", "forecast", "temperature", "rain", "openweather"], popular=60,
       domains=["openweathermap.org"], docs_url="https://openweathermap.org/api",
       actions=[_get("weather", "/weather", "Current weather for a place", {"q": "city name", "units": "metric|imperial"}),
                _get("forecast", "/forecast", "Five-day forecast", {"q": "city name", "units": "metric|imperial"})]),
    _c("open_meteo", "Open-Meteo", "knowledge", "rest", "Weather forecasts for any coordinates. No key.",
       base_url="https://api.open-meteo.com/v1", auth={"type": "none"}, can=["forecast for a place"],
       color="#ff9f0a", mark="☂", keywords=["weather", "forecast", "open-meteo", "temperature"], popular=50,
       domains=["open-meteo.com"], docs_url="https://open-meteo.com/en/docs",
       actions=[_get("forecast", "/forecast", "Forecast",
                     {"latitude": "e.g. 40.71", "longitude": "e.g. -74.01",
                      "current": "temperature_2m,precipitation,wind_speed_10m",
                      "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum", "timezone": "auto"})]),
    _c("wolfram_alpha", "Wolfram|Alpha", "knowledge", "rest", "Exact answers to maths, science and data questions.",
       base_url="https://api.wolframalpha.com", auth={"type": "query", "param": "appid"},
       fields=[_secret("token", "App ID", "https://developer.wolframalpha.com/access")],
       can=["a short exact answer"], color="#ff6600", mark="✸",
       keywords=["wolfram", "wolfram alpha", "math", "calculate", "convert", "integral"], popular=55,
       domains=["wolframalpha.com"], docs_url="https://products.wolframalpha.com/short-answers-api/documentation",
       actions=[_get("answer", "/v1/result", "A short answer in plain text", {"i": "the question"})]),
    _c("nasa", "NASA", "knowledge", "rest", "Astronomy Picture of the Day and near-Earth objects.",
       base_url="https://api.nasa.gov", auth={"type": "query", "param": "api_key"},
       fields=[_secret("token", "API key (DEMO_KEY works for a few calls)", "https://api.nasa.gov/")],
       can=["picture of the day", "near-Earth asteroids"], color="#fc3d21", mark="✦",
       keywords=["nasa", "space", "astronomy", "apod", "asteroid"], popular=35, domains=["nasa.gov"],
       docs_url="https://api.nasa.gov/",
       actions=[_get("apod", "/planetary/apod", "Astronomy Picture of the Day", {"date": "YYYY-MM-DD"}),
                _get("asteroids", "/neo/rest/v1/feed", "Near-Earth objects", {"start_date": "YYYY-MM-DD",
                                                                              "end_date": "within 7 days"})]),

    # --- Automation -----------------------------------------------------------------------------------------------
    _webhook("zapier", "Zapier", "Start a Zap: Nyx sends data to your Zap's “Catch Hook” address.",
             domains=["hooks.zapier.com"], help_url="https://help.zapier.com/hc/en-us/articles/8496288690317",
             color="#ff4f00", mark="Z", keywords=["zapier", "zap"], placeholder="https://hooks.zapier.com/hooks/catch/…"),
    _webhook("make", "Make", "Start a Make scenario with its custom webhook address.",
             domains=["make.com"], help_url="https://www.make.com/en/help/tools/webhooks",
             color="#a63bff", mark="M", keywords=["make", "integromat", "scenario"],
             placeholder="https://hook.us1.make.com/…"),
    _webhook("n8n", "n8n", "Start an n8n workflow with its Webhook node's production address.",
             domains=[], help_url="https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/",
             color="#ea4b71", mark="n8", keywords=["n8n"], placeholder="https://your-n8n.example.com/webhook/…"),
    _c("ifttt", "IFTTT", "automation", "rest", "Trigger an IFTTT applet with the Webhooks service.",
       base_url="https://maker.ifttt.com", auth={"type": "none"},
       fields=[_secret("key", "Webhooks key", "https://ifttt.com/maker_webhooks/settings")],
       can=["trigger an applet"], color="#33ccff", mark="if", keywords=["ifttt", "applet", "trigger"], popular=40,
       domains=["ifttt.com"], docs_url="https://ifttt.com/maker_webhooks",
       actions=[_a("trigger", "POST", "/trigger/{event}/json/with/key/{key}", "Trigger an applet",
                   {"event": "the event name in your applet", "value1": "optional data"}, write=True)]),

    # --- Remote MCP servers that need no account -------------------------------------------------------------------
    _c("deepwiki", "DeepWiki", "mcp", "mcp", "Ask questions about any public GitHub repository's code and docs.",
       mcp_url="https://mcp.deepwiki.com/mcp", auth={"type": "none"}, can=["explain a repository", "answer questions about code"],
       color="#64d2ff", mark="DW", keywords=["deepwiki", "repository docs", "codebase"], popular=45,
       domains=["deepwiki.com"], docs_url="https://docs.devin.ai/work-with-devin/deepwiki-mcp"),
    _c("microsoft_learn", "Microsoft Learn", "mcp", "mcp", "Search Microsoft's official documentation.",
       mcp_url="https://learn.microsoft.com/api/mcp", auth={"type": "none"}, can=["search Microsoft docs", "fetch a docs page"],
       color="#00a4ef", mark="ML", keywords=["microsoft docs", "azure docs", ".net docs", "microsoft learn"], popular=40,
       domains=["learn.microsoft.com"], docs_url="https://learn.microsoft.com/training/support/mcp"),
    _c("context7", "Context7", "mcp", "mcp", "Up-to-date documentation for programming libraries.",
       mcp_url="https://mcp.context7.com/mcp", auth={"type": "none"}, can=["find a library", "read its current docs"],
       color="#2dd4bf", mark="C7", keywords=["context7", "library docs", "api docs", "framework docs"], popular=45,
       domains=["context7.com"], docs_url="https://context7.com/"),

    # --- Starters for the owner's own connectors (they open the Add sheet) ----------------------------------------
    _c("custom_website", "Any website", "custom", "website", "Give Nyx a site's address so it can read it when asked.",
       template=True, auth={"type": "none"}, can=["read the site's pages"], color="#a594ff", mark="www",
       keywords=["website", "site", "url", "web page"], popular=30),
    _c("custom_rest", "Any API", "custom", "rest", "Connect any HTTPS API with its address and key.",
       template=True, can=["call its endpoints"], color="#a594ff", mark="{ }", keywords=["api", "rest", "endpoint"], popular=30),
    _c("custom_mcp", "Any MCP server", "custom", "mcp", "Connect a remote MCP server by its https address.",
       template=True, can=["use the server's tools"], color="#a594ff", mark="MCP",
       keywords=["mcp", "model context protocol", "mcp server"], popular=30),
    _c("custom_webhook", "Any webhook", "custom", "webhook", "Send data to any https webhook address.",
       template=True, auth={"type": "none"}, can=["send it data"], color="#a594ff", mark="↗",
       keywords=["webhook"], popular=25),
]

#: Remote MCP servers Nyx recognises when the owner pastes their address or names them in "Add any".
#: ``auth``: none (just works), bearer (paste a token), oauth (needs a browser sign-in Nyx can't do for MCP yet).
KNOWN_MCP: List[Dict[str, str]] = [
    {"name": "DeepWiki", "url": "https://mcp.deepwiki.com/mcp", "auth": "none", "catalog": "deepwiki"},
    {"name": "Microsoft Learn", "url": "https://learn.microsoft.com/api/mcp", "auth": "none", "catalog": "microsoft_learn"},
    {"name": "Context7", "url": "https://mcp.context7.com/mcp", "auth": "none", "catalog": "context7"},
    {"name": "GitHub MCP", "url": "https://api.githubcopilot.com/mcp/", "auth": "bearer",
     "help_url": "https://github.com/settings/personal-access-tokens", "rest": "github"},
    {"name": "Hugging Face MCP", "url": "https://huggingface.co/mcp", "auth": "bearer",
     "help_url": "https://huggingface.co/settings/tokens", "rest": "huggingface"},
    {"name": "Stripe MCP", "url": "https://mcp.stripe.com", "auth": "bearer",
     "help_url": "https://dashboard.stripe.com/apikeys", "rest": "stripe"},
    {"name": "Notion MCP", "url": "https://mcp.notion.com/mcp", "auth": "oauth", "rest": "notion"},
    {"name": "Linear MCP", "url": "https://mcp.linear.app/mcp", "auth": "oauth", "rest": "linear"},
    {"name": "Vercel MCP", "url": "https://mcp.vercel.com", "auth": "oauth", "rest": "vercel"},
    {"name": "Atlassian MCP", "url": "https://mcp.atlassian.com/v1/sse", "auth": "oauth", "rest": "jira"},
    {"name": "Sentry MCP", "url": "https://mcp.sentry.dev/mcp", "auth": "oauth", "rest": ""},
]

_BY_ID: Dict[str, Dict[str, Any]] = {e["id"]: e for e in _ENTRIES}


# ---------------------------------------------------------------------------
# Reading the catalogue
# ---------------------------------------------------------------------------

def _copy(entry: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(entry))


def _custom() -> List[Dict[str, Any]]:
    try:
        import connector_builder

        return [e for e in connector_builder.custom_connectors() if isinstance(e, dict) and e.get("id")]
    except Exception:  # pragma: no cover - a broken custom store must not hide the catalogue
        return []


def list_catalog(include_custom: bool = True) -> List[Dict[str, Any]]:
    """Every connector, catalogue first, then the owner's own (``origin: "custom"``). Copies; safe to change."""
    out = [_copy(e) for e in _ENTRIES]
    if include_custom:
        known = set(_BY_ID)
        out += [e for e in _custom() if str(e["id"]).lower() not in known]
    return out


def get(connector_id: str) -> Optional[Dict[str, Any]]:
    key = str(connector_id or "").strip().lower()
    if key in _BY_ID:
        return _copy(_BY_ID[key])
    return next((e for e in _custom() if str(e.get("id", "")).lower() == key), None)


def categories() -> List[Dict[str, str]]:
    return [dict(c) for c in CATEGORIES]


def _host(url: str) -> str:
    try:
        return (urlparse(url if "//" in url else "https://" + url).hostname or "").lower()
    except ValueError:
        return ""


def find_by_url(url: str) -> Optional[Dict[str, Any]]:
    """The catalogue entry a pasted address belongs to (vercel.com/… → Vercel), if any."""
    host = _host(url)
    if not host:
        return None
    for entry in _ENTRIES:
        if entry.get("template"):
            continue
        for domain in entry.get("domains") or []:
            if host == domain or host.endswith("." + domain):
                return _copy(entry)
        if entry.get("mcp_url") and _host(entry["mcp_url"]) == host:
            return _copy(entry)
    return None


def known_mcp(text: str) -> Optional[Dict[str, str]]:
    """A remote MCP server the owner named or pasted ("github mcp", https://mcp.deepwiki.com/mcp)."""
    lowered = (text or "").lower()
    for server in KNOWN_MCP:
        if server["url"].rstrip("/").lower() in lowered or (_host(server["url"]) and _host(server["url"]) in lowered):
            return dict(server)
    for server in KNOWN_MCP:
        if server["name"].lower() in lowered:
            return dict(server)
    return None


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------

def _store_path():
    return data_path("connectors/connections.json")


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: Dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def _secret_name(connector_id: str, field: str) -> str:
    return f"connector:{connector_id}:{field}"


def _get_secret(name: str) -> str:
    try:
        from secret_store import get_keys

        values = get_keys(name)
        return values[0] if values else ""
    except Exception:  # pragma: no cover
        return ""


def _set_secret(name: str, value: str) -> None:
    from secret_store import set_keys

    set_keys(name, [value] if value else [])


def _google_accounts(product: str) -> List[str]:
    try:
        import google_oauth

        return list(google_oauth.accounts_for(product))
    except Exception:
        return []


def _microsoft_accounts(product: str) -> List[str]:
    try:
        from connectors import microsoft_graph

        return list(microsoft_graph.accounts_for(product))
    except Exception:
        return []


def _mail_accounts(provider: str = "") -> List[str]:
    """Mailboxes the email tools can use (app password or Google sign-in), optionally one provider's."""
    try:
        import email_client

        return [a["address"] for a in email_client.list_accounts()
                if a.get("configured") and (not provider or a.get("provider") == provider)]
    except Exception:
        return []


def _registry_available(name: str) -> bool:
    if name == "email":
        return bool(_mail_accounts())
    try:
        from connectors import CONNECTOR_REGISTRY

        return bool(CONNECTOR_REGISTRY.is_available(name))
    except Exception:
        return False


def _model_spec_for(entry: Dict[str, Any]) -> str:
    """The name of a provider spec the owner added for this company (matched by API host), or ""."""
    host = _host(str(entry.get("chat_url") or ""))
    try:
        from provider_specs import PROVIDER_SPECS

        for spec in PROVIDER_SPECS.list_specs():
            if host and _host(spec.chat_url) == host:
                return spec.name
    except Exception:
        pass
    return ""


def _custom_connected(connector_id: str) -> bool:
    try:
        import connector_builder

        return connector_builder.is_connected(connector_id)
    except Exception:
        return False


def is_connected(connector_id: str) -> bool:
    """Whether the owner can use this connector right now. Never raises."""
    entry = get(connector_id)
    if entry is None:
        return False
    key = str(entry["id"]).lower()
    kind = entry.get("kind")
    try:
        if entry.get("origin") == "custom":
            return _custom_connected(key)
        if entry.get("template"):
            return False
        if kind == "oauth_google":
            product = str(entry.get("google_product"))
            return bool(_google_accounts(product) or (product == "gmail" and _mail_accounts("gmail")))
        if kind == "oauth_microsoft":
            return bool(_microsoft_accounts(str(entry.get("microsoft_product"))))
        if kind == "builtin":
            return _registry_available(str(entry.get("registry") or key))
        if kind == "provider":
            import model_hub

            return bool(model_hub.is_configured(str(entry.get("provider"))))
        if kind == "model":
            return bool(_model_spec_for(entry))
        return key in _read()
    except Exception:  # noqa: BLE001 - a status check must never break a listing or a turn
        return False


def connection_values(connector_id: str) -> Dict[str, Any]:
    """The saved values for a connector, secrets included. Server-side only — never put this in a response."""
    entry = get(connector_id)
    if entry is None:
        return {}
    key = str(entry["id"]).lower()
    kind = entry.get("kind")
    if entry.get("origin") == "custom":
        try:
            import connector_builder

            return connector_builder.connection_values(key)
        except Exception:  # pragma: no cover
            return {}
    try:
        if kind == "oauth_google":
            accounts = _google_accounts(str(entry.get("google_product")))
            if not accounts:
                return {}
            import google_oauth

            return {"access_token": google_oauth.access_token(accounts[0]), "account": accounts[0]}
        if kind == "oauth_microsoft":
            accounts = _microsoft_accounts(str(entry.get("microsoft_product")))
            if not accounts:
                return {}
            from connectors import microsoft_graph

            return {"access_token": microsoft_graph.access_token(accounts[0]), "account": accounts[0]}
        if kind == "provider":
            import model_hub

            token = model_hub.api_key_for(str(entry.get("provider")))
            return {"api_key": token} if token else {}
        if kind == "model":
            name = _model_spec_for(entry)
            if not name:
                return {}
            from provider_specs import PROVIDER_SPECS

            spec = PROVIDER_SPECS.get(name)
            token = _get_secret(spec.api_key_name) if spec is not None and spec.api_key_name else ""
            return {"api_key": token} if token else {}
    except Exception:  # noqa: BLE001 - an expired sign-in means "no values", which the caller explains
        return {}
    saved = _read().get(key)
    if not isinstance(saved, dict):
        return {}
    values = dict(saved.get("fields") or {})
    for name in saved.get("secret_fields") or []:
        value = _get_secret(_secret_name(key, name))
        if value:
            values[name] = value
    return values


def _normalise(field: Dict[str, Any], value: str) -> str:
    """Forgive the usual paste mistakes: a whole address where a site name was asked for."""
    text = value.strip()
    if field.get("kind") == "subdomain":
        text = re.sub(r"^[a-z]+://", "", text, flags=re.I).split("/")[0]
        suffix = str(field.get("suffix") or "")
        if suffix and text.lower().endswith(suffix):
            text = text[: -len(suffix)]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,62}", text):
            raise ValueError(f"{field.get('label')} should look like your-name, not {value.strip()[:40]!r}.")
    elif field.get("kind") == "choice" and field.get("choices") and text not in field["choices"]:
        raise ValueError(f"{field.get('label')} must be one of: {', '.join(field['choices'])}.")
    elif field.get("key") == "webhook_url" or field.get("kind") == "url":
        if not text.lower().startswith("https://"):
            raise ValueError(f"{field.get('label')} must be an https:// address.")
    return text


def _check_webhook(entry: Dict[str, Any], url: str) -> None:
    allowed = [d for d in entry.get("domains") or [] if d]
    host = _host(url)
    if allowed and not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValueError(f"That isn't a {entry['name']} address — it should be on {' or '.join(allowed)}.")


def connect(connector_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Save the owner's connection to a catalogue entry. Plain values to the store, secrets to ``secret_store``.

    Raises ``ValueError`` with a sentence the owner can act on (a missing field, a sign-in that happens elsewhere).
    """
    entry = get(connector_id)
    if entry is None:
        raise ValueError(f"There is no connector called {connector_id!r}.")
    key = str(entry["id"]).lower()
    kind = entry.get("kind")
    if entry.get("template"):
        raise ValueError(f"{entry['name']} is a starter: say what to add and Nyx builds the connector.")
    if kind == "oauth_google":
        raise ValueError(f"{entry['name']} connects with Sign in with Google.")
    if kind == "oauth_microsoft":
        raise ValueError(f"{entry['name']} connects with Sign in with Microsoft.")
    if kind == "builtin":
        if is_connected(key):
            return status(key)
        raise ValueError(entry.get("note") or f"{entry['name']} is built into Nyx and needs no account.")
    if kind == "model":
        import connector_builder

        try:
            connector_builder.add(catalog_id=key, fields=dict(values or {}))
        except connector_builder.BuilderError as error:
            raise ValueError(str(error)) from None
        return status(key)
    clean = {str(k): str(v or "").strip() for k, v in (values or {}).items()}
    fields = {str(f["key"]): f for f in entry.get("fields") or []}
    for name, field in fields.items():
        if clean.get(name):
            clean[name] = _normalise(field, clean[name])
        elif field.get("default"):
            clean[name] = str(field["default"])
    saved = _read().get(key) if kind != "provider" else None
    already = set((saved or {}).get("secret_fields") or []) | set((saved or {}).get("fields") or {})
    missing = [str(f.get("label") or n) for n, f in fields.items()
               if f.get("required") and not clean.get(n) and n not in already]
    if missing:
        raise ValueError("Still needed: " + ", ".join(missing) + ".")
    if kind == "webhook" and clean.get("webhook_url"):
        _check_webhook(entry, clean["webhook_url"])
    if kind == "provider":
        token = clean.get("api_key", "")
        if len(token) < 8:
            raise ValueError("That key looks too short to be real.")
        from routes_models import store_provider_key

        store_provider_key(str(entry["provider"]), token)
        return status(key)
    with _lock:
        store = _read()
        record = dict(store.get(key) or {"fields": {}, "secret_fields": []})
        plain = dict(record.get("fields") or {})
        secret_names = list(record.get("secret_fields") or [])
        for name, value in clean.items():
            if not value or name not in fields:
                continue
            if fields[name].get("secret"):
                _set_secret(_secret_name(key, name), value)
                if name not in secret_names:
                    secret_names.append(name)
            else:
                plain[name] = value[:500]
        store[key] = {"fields": plain, "secret_fields": secret_names,
                      "connected_at": record.get("connected_at") or time.time(), "updated_at": time.time()}
        _write(store)
    _changed(key)
    return status(key)


def disconnect(connector_id: str, account: str = "") -> bool:
    """Forget a connection and its secrets, wherever that connection lives.

    A Google or Microsoft sign-in covers every app of that company for the account, so signing out of one signs
    out of all of them — the UI says so before it asks. An AI provider's key is removed from Keys & Models.
    """
    entry = get(connector_id)
    key = str((entry or {}).get("id") or connector_id or "").lower()
    kind = (entry or {}).get("kind")
    if entry is not None and entry.get("origin") == "custom":
        import connector_builder

        removed = connector_builder.disconnect(key)
        _changed(key)
        return removed
    if kind == "oauth_google":
        accounts = [a for a in _google_accounts(str(entry.get("google_product"))) if not account or a == account]
        import google_oauth

        for address in accounts:
            google_oauth.disconnect(address)
        _changed(key)
        return bool(accounts)
    if kind == "oauth_microsoft":
        from connectors import microsoft_graph

        accounts = [a for a in _microsoft_accounts(str(entry.get("microsoft_product"))) if not account or a == account]
        for name in accounts:
            microsoft_graph.disconnect(name)
        _changed(key)
        return bool(accounts)
    if kind == "provider":
        from routes_models import delete_provider_key

        delete_provider_key(str(entry.get("provider")))
        _changed(key)
        return True
    with _lock:
        store = _read()
        saved = store.pop(key, None)
        if saved is None:
            return False
        _write(store)
    for name in saved.get("secret_fields") or []:
        try:
            _set_secret(_secret_name(key, name), "")
        except Exception:  # pragma: no cover
            pass
    _changed(key)
    return True


def status(connector_id: str) -> Dict[str, Any]:
    """What the UI shows for one connector's connection. Secrets appear only as their last four characters."""
    entry = get(connector_id) or {"id": connector_id, "kind": "rest"}
    key = str(entry["id"]).lower()
    kind = entry.get("kind")
    out: Dict[str, Any] = {"connected": is_connected(key), "accounts": [], "saved": {}, "connected_at": None, "how": ""}
    if kind == "oauth_google":
        product = str(entry.get("google_product"))
        out["accounts"] = _google_accounts(product)
        mail = _mail_accounts("gmail") if product == "gmail" else []
        out["mail_accounts"] = [a for a in mail if a not in out["accounts"]]
        out["how"] = "Google sign-in" if out["accounts"] else ("app password" if mail else "")
    elif kind == "oauth_microsoft":
        out["accounts"] = _microsoft_accounts(str(entry.get("microsoft_product")))
        out["how"] = "Microsoft sign-in" if out["accounts"] else ""
    elif kind == "builtin":
        out["how"] = "built in"
        if entry.get("registry") == "email":
            out["accounts"] = _mail_accounts()
    elif kind == "provider":
        try:
            import model_hub

            token = model_hub.api_key_for(str(entry.get("provider")))
            out["saved"] = {"api_key": "•••• " + token[-4:]} if len(token) >= 8 else {}
        except Exception:
            pass
        out["how"] = "Keys & Models"
    elif kind == "model":
        name = _model_spec_for(entry)
        out["how"] = f"model “{name}”" if name else ""
    elif entry.get("origin") != "custom":
        saved = _read().get(key) or {}
        out["connected_at"] = saved.get("connected_at")
        hints = {k: str(v)[:80] for k, v in (saved.get("fields") or {}).items()}
        for name in saved.get("secret_fields") or []:
            value = _get_secret(_secret_name(key, name))
            hints[name] = ("•••• " + value[-4:]) if len(value) >= 8 else ("saved" if value else "")
        out["saved"] = hints
    return out


def public(entry: Dict[str, Any], *, detail: bool = False) -> Dict[str, Any]:
    """An entry as the Connectors tab shows it: everything but secrets, plus its connection state."""
    shown = {k: v for k, v in entry.items() if k not in ("actions",)}
    actions = list(entry.get("actions") or [])
    shown["action_count"] = len(actions)
    shown["actions"] = actions if detail else [{"id": a.get("id"), "description": a.get("description"),
                                                "write": bool(a.get("write"))} for a in actions]
    shown.update(status(str(entry["id"])))
    shown.setdefault("origin", "catalog")
    return shown


def _changed(connector_id: str) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("connectors.changed", id=connector_id)
    except Exception:  # pragma: no cover
        pass
