# Nyx Ichos for VS Code

Edit, explain and chat about code with Nyx. Every change Nyx suggests opens as a diff first; **Accept** applies it
inside VS Code (so Ctrl+Z undoes it), **Reject** throws it away.

## Install (no build step)

1. Start Nyx (the Nyx Ichos desktop shortcut, or `Start Nyx.bat`).
2. In PowerShell, from this folder:

   ```powershell
   .\install.ps1
   ```

   It copies this folder to `%USERPROFILE%\.vscode\extensions\shagnik.nyx-ichos-0.1.0`. Restart VS Code.

## Use

| Command | Shortcut | What it does |
|---|---|---|
| Nyx: Edit with Instruction | Ctrl+Alt+E (also right-click) | Select lines (or none for the whole file), say what to change, review the diff, Accept or Reject |
| Nyx: Ask About This Code | right-click | Explains the file or selection, or answers your question |
| Nyx: Open Chat | Ctrl+Alt+N, or click “Nyx” in the status bar | A chat beside your code; with “Include the open file” on, Nyx sees the file and selection and can edit with its tools |
| Nyx: Open This Folder in Nyx's Code Tab | | Adds the folder to Nyx's Code tab and opens Nyx |
| Nyx: Sign In | | Only needed after you created a Nyx account (a claimed install) |

Nyx only reads and edits inside folders you opened this way. The engine address is the `nyx.serverUrl` setting
(default `http://127.0.0.1:8000`).
