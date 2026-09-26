// Nyx Ichos for VS Code (Request G7). Plain JavaScript on purpose: no build step, so the folder is the extension.
//
// Every edit is a proposal from Nyx's engine (/api/code/propose). VS Code shows it as a diff; Accept applies it
// inside the editor with a normal WorkspaceEdit, so Ctrl+Z and unsaved-changes still behave like VS Code.
"use strict";

const vscode = require("vscode");

const PROPOSAL_SCHEME = "nyx-proposal";
const proposals = new Map(); // proposal id -> proposed full text

function serverUrl() {
  return String(vscode.workspace.getConfiguration("nyx").get("serverUrl") || "http://127.0.0.1:8000").replace(/\/+$/, "");
}

let secrets;
async function call(path, { method = "GET", body, timeoutMs = 120000 } = {}) {
  const token = secrets ? await secrets.get("nyx.token") : undefined;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(serverUrl() + path, {
      method,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    throw new Error(error.name === "AbortError" ? "Nyx took too long to answer." : "Nyx's engine isn't running. Start Nyx, then try again.");
  } finally {
    clearTimeout(timer);
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) throw new Error("Nyx needs you to sign in — run “Nyx: Sign In”.");
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Nyx answered ${response.status}.`);
  return data;
}

/** Make sure Nyx may read this file: open its workspace folder (or the file itself) in the engine. */
async function ensureWorkspace(uri) {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  await call("/api/code/workspaces", { method: "POST", body: { path: folder ? folder.uri.fsPath : uri.fsPath } });
}

function selectionLines(editor) {
  const sel = editor.selection;
  if (sel.isEmpty) return {};
  const endLine = sel.end.character === 0 && sel.end.line > sel.start.line ? sel.end.line : sel.end.line + 1;
  return { start_line: sel.start.line + 1, end_line: endLine };
}

async function editSelection() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme !== "file") {
    vscode.window.showWarningMessage("Open a saved file first.");
    return;
  }
  const instruction = await vscode.window.showInputBox({
    title: "Nyx: Edit with Instruction",
    prompt: editor.selection.isEmpty ? "What should change in this file?" : "What should change in the selected lines?",
    placeHolder: "e.g. add input validation and a docstring",
  });
  if (!instruction) return;
  if (editor.document.isDirty) await editor.document.save();
  const document = editor.document;

  await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Nyx is writing the change…" }, async () => {
    try {
      await ensureWorkspace(document.uri);
      const { proposal } = await call("/api/code/propose", {
        method: "POST",
        body: { path: document.uri.fsPath, instruction, ...selectionLines(editor) },
      });
      const full = await call(`/api/code/proposals/${proposal.id}`);
      proposals.set(proposal.id, full.proposal.new_text);
      const right = vscode.Uri.parse(`${PROPOSAL_SCHEME}:/${proposal.id}/${encodeURIComponent(proposal.name)}`);
      await vscode.commands.executeCommand("vscode.diff", document.uri, right, `Nyx: ${instruction} (+${proposal.added} −${proposal.removed})`);
      const choice = await vscode.window.showInformationMessage(
        `${proposal.explanation || "Nyx proposed a change."} (${proposal.model})`, { modal: false }, "Accept", "Reject");
      if (choice === "Accept") {
        const edit = new vscode.WorkspaceEdit();
        const whole = new vscode.Range(document.positionAt(0), document.positionAt(document.getText().length));
        edit.replace(document.uri, whole, full.proposal.new_text);
        await vscode.workspace.applyEdit(edit);
        await document.save();
        await call(`/api/code/proposals/${proposal.id}/resolve`, { method: "POST", body: { status: "applied_in_editor" } });
        await vscode.commands.executeCommand("workbench.action.closeActiveEditor");
        vscode.window.showTextDocument(document);
        vscode.window.setStatusBarMessage("Nyx: change applied — Ctrl+Z undoes it", 5000);
      } else {
        await call(`/api/code/proposals/${proposal.id}/resolve`, { method: "POST", body: { status: "rejected" } });
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Nyx: ${error.message}`);
    }
  });
}

async function ask() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme !== "file") {
    vscode.window.showWarningMessage("Open a saved file first.");
    return;
  }
  const question = await vscode.window.showInputBox({ title: "Nyx: Ask About This Code", placeHolder: "Leave empty to explain it" });
  if (question === undefined) return;
  await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: "Nyx is reading…" }, async () => {
    try {
      await ensureWorkspace(editor.document.uri);
      const result = await call("/api/code/ask", { method: "POST", body: { path: editor.document.uri.fsPath, question, ...selectionLines(editor) } });
      const doc = await vscode.workspace.openTextDocument({ language: "markdown", content: `# Nyx on ${editor.document.fileName.split(/[\\/]/).pop()}\n\n_${result.model}_\n\n${result.answer}\n` });
      await vscode.commands.executeCommand("markdown.showPreviewToSide", doc.uri).then(undefined, () => vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside));
    } catch (error) {
      vscode.window.showErrorMessage(`Nyx: ${error.message}`);
    }
  });
}

function chatHtml(nonce) {
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); margin: 0; display: flex; flex-direction: column; height: 100vh; }
  #log { flex: 1; overflow-y: auto; padding: 10px 12px; }
  .msg { margin: 0 0 10px; white-space: pre-wrap; line-height: 1.5; }
  .me { color: var(--vscode-textLink-foreground); }
  .meta { opacity: .7; font-size: 11px; }
  form { display: flex; gap: 6px; padding: 8px; border-top: 1px solid var(--vscode-panel-border); }
  textarea { flex: 1; resize: none; font: inherit; color: var(--vscode-input-foreground); background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border, transparent); padding: 6px; }
  button { font: inherit; color: var(--vscode-button-foreground); background: var(--vscode-button-background); border: 0; padding: 0 14px; }
  label { display: flex; gap: 4px; align-items: center; font-size: 12px; padding: 4px 10px 0; opacity: .85; }
</style></head><body>
<div id="log"><p class="msg meta">Ask Nyx anything. With “Include the open file” on, Nyx sees the file path and your selection and can edit files with its tools.</p></div>
<label><input type="checkbox" id="ctx" checked> Include the open file</label>
<form id="f"><textarea id="t" rows="3" placeholder="Message Nyx (Ctrl+Enter to send)"></textarea><button>Send</button></form>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  const log = document.getElementById('log'), t = document.getElementById('t');
  function add(text, cls) { const p = document.createElement('p'); p.className = 'msg ' + (cls || ''); p.textContent = text; log.appendChild(p); log.scrollTop = log.scrollHeight; return p; }
  document.getElementById('f').addEventListener('submit', (e) => { e.preventDefault(); const text = t.value.trim(); if (!text) return; add(text, 'me'); t.value = ''; vscode.postMessage({ type: 'send', text, withFile: document.getElementById('ctx').checked }); window.pending = add('Nyx is thinking…', 'meta'); });
  t.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); document.getElementById('f').requestSubmit(); } });
  window.addEventListener('message', (e) => { const m = e.data; if (window.pending) { window.pending.remove(); window.pending = null; } add(m.text, m.error ? 'meta' : ''); if (m.meta) add(m.meta, 'meta'); });
</script></body></html>`;
}

let chatPanel;
let chatId;
function openChat(context) {
  if (chatPanel) { chatPanel.reveal(); return; }
  chatPanel = vscode.window.createWebviewPanel("nyxChat", "Nyx", vscode.ViewColumn.Beside, { enableScripts: true, retainContextWhenHidden: true });
  const nonce = Math.random().toString(36).slice(2) + Date.now().toString(36);
  chatPanel.webview.html = chatHtml(nonce);
  chatPanel.onDidDispose(() => { chatPanel = undefined; }, null, context.subscriptions);
  chatPanel.webview.onDidReceiveMessage(async (message) => {
    if (message.type !== "send") return;
    let text = message.text;
    const editor = vscode.window.visibleTextEditors.find((e) => e.document.uri.scheme === "file");
    if (message.withFile && editor) {
      const lines = selectionLines(editor);
      const selected = editor.selection.isEmpty ? "" : `\nSelected (lines ${lines.start_line}–${lines.end_line}):\n\`\`\`\n${editor.document.getText(editor.selection).slice(0, 6000)}\n\`\`\``;
      text = `[VS Code] Open file: ${editor.document.uri.fsPath}${selected}\n\n${text}`;
    }
    try {
      if (!chatId) chatId = (await call("/api/chats", { method: "POST", body: { title: "VS Code" } })).chat.id;
      const reply = await call("/api/chat", { method: "POST", body: { message: text, chat_id: chatId }, timeoutMs: 600000 });
      chatPanel && chatPanel.webview.postMessage({ text: reply.reply || reply.response || JSON.stringify(reply), meta: reply.provider ? `— ${reply.provider}` : "" });
    } catch (error) {
      chatPanel && chatPanel.webview.postMessage({ text: error.message, error: true });
    }
  });
}

async function openInNyx() {
  const editor = vscode.window.activeTextEditor;
  const folder = editor ? vscode.workspace.getWorkspaceFolder(editor.document.uri) : vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
  const target = folder ? folder.uri.fsPath : editor && editor.document.uri.fsPath;
  if (!target) { vscode.window.showWarningMessage("Open a folder first."); return; }
  try {
    await call("/api/code/workspaces", { method: "POST", body: { path: target } });
    vscode.env.openExternal(vscode.Uri.parse(serverUrl() + "/"));
    vscode.window.showInformationMessage("Opened in Nyx — pick the Code tab.");
  } catch (error) {
    vscode.window.showErrorMessage(`Nyx: ${error.message}`);
  }
}

async function signIn() {
  const email = await vscode.window.showInputBox({ title: "Nyx: Sign In", prompt: "Your Nyx account email" });
  if (!email) return;
  const password = await vscode.window.showInputBox({ title: "Nyx: Sign In", prompt: "Password", password: true });
  if (!password) return;
  try {
    const result = await call("/api/auth/login", { method: "POST", body: { email, password } });
    const token = result.token || result.session_token;
    if (!token) throw new Error("Signed in, but no session came back.");
    await secrets.store("nyx.token", token);
    vscode.window.showInformationMessage("Signed in to Nyx.");
  } catch (error) {
    vscode.window.showErrorMessage(`Nyx: ${error.message}`);
  }
}

function activate(context) {
  secrets = context.secrets;
  context.subscriptions.push(
    vscode.workspace.registerTextDocumentContentProvider(PROPOSAL_SCHEME, {
      provideTextDocumentContent: (uri) => proposals.get(uri.path.split("/")[1]) || "",
    }),
    vscode.commands.registerCommand("nyx.editSelection", editSelection),
    vscode.commands.registerCommand("nyx.ask", ask),
    vscode.commands.registerCommand("nyx.chat", () => openChat(context)),
    vscode.commands.registerCommand("nyx.openInNyx", openInNyx),
    vscode.commands.registerCommand("nyx.signIn", signIn),
  );

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.command = "nyx.chat";
  context.subscriptions.push(status);
  const refresh = async () => {
    try {
      await call("/api/health", { timeoutMs: 3000 });
      status.text = "$(sparkle) Nyx";
      status.tooltip = "Nyx is running — click to chat, Ctrl+Alt+E to edit";
    } catch {
      status.text = "$(circle-slash) Nyx";
      status.tooltip = "Nyx's engine isn't running";
    }
    status.show();
  };
  refresh();
  const timer = setInterval(refresh, 30000);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });
}

function deactivate() {}

module.exports = { activate, deactivate };
