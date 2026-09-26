"""The template catalog: static starter files, tab specs, documents and prompts (Request S11).

"Add templates for every coding, websites and more. This is a jack of all trades." Everything here is
data. Files are written only into a folder the owner chose and are never run by Nyx; tab templates are
validated ``dynamic_tabs`` specs. ``{{name}}`` is replaced with the project name when a template is used.
Kept deliberately short — a clean skeleton to build on, not a framework (the owner wants Nyx small).
"""

from __future__ import annotations

from typing import Any, Dict, List

T: List[Dict[str, Any]] = []


def files(tid: str, category: str, title: str, description: str, tags: str, content: Dict[str, str]) -> None:
    T.append({"id": tid, "category": category, "kind": "files", "title": title, "description": description,
              "tags": tags.split(), "files": content})


def doc(tid: str, title: str, description: str, tags: str, text: str, category: str = "Documents") -> None:
    T.append({"id": tid, "category": category, "kind": "doc", "title": title, "description": description,
              "tags": tags.split(), "text": text.strip() + "\n"})


def tab(tid: str, title: str, description: str, tags: str, icon: str, blocks: List[Dict[str, Any]]) -> None:
    T.append({"id": tid, "category": "Tabs", "kind": "tab", "title": title, "description": description,
              "tags": tags.split(), "spec": {"label": title, "icon": icon, "description": description, "blocks": blocks}})


def prompt(tid: str, title: str, tags: str, text: str) -> None:
    doc(tid, title, "A prompt to paste into any chat.", tags, text, category="Prompts")


README = "# {{name}}\n\nWhat it does, in one sentence.\n\n## Run\n\n```\n{run}\n```\n"
GITIGNORE_PY = "__pycache__/\n*.pyc\n.venv/\n.env\ndist/\nbuild/\n"
GITIGNORE_NODE = "node_modules/\ndist/\n.env\n"

# --- code ---------------------------------------------------------------------------------------

files("python-cli", "Code", "Python command-line tool", "argparse CLI with a main() and a test.", "python cli", {
    "{{name}}/__init__.py": "",
    "{{name}}/__main__.py": "import argparse\n\n\ndef main(argv=None) -> int:\n    parser = argparse.ArgumentParser(prog=\"{{name}}\")\n    parser.add_argument(\"name\", nargs=\"?\", default=\"world\")\n    args = parser.parse_args(argv)\n    print(f\"Hello, {args.name}!\")\n    return 0\n\n\nif __name__ == \"__main__\":\n    raise SystemExit(main())\n",
    "tests/test_main.py": "from {{name}}.__main__ import main\n\n\ndef test_main(capsys):\n    assert main([\"Nyx\"]) == 0\n    assert \"Nyx\" in capsys.readouterr().out\n",
    "README.md": README.replace("{run}", "python -m {{name}} you"), ".gitignore": GITIGNORE_PY})
files("fastapi-api", "Code", "FastAPI web API", "A JSON API with one resource and health check.", "python api fastapi backend", {
    "main.py": "from fastapi import FastAPI, HTTPException\nfrom pydantic import BaseModel\n\napp = FastAPI(title=\"{{name}}\")\nitems: dict[int, dict] = {}\n\n\nclass Item(BaseModel):\n    name: str\n    price: float = 0.0\n\n\n@app.get(\"/health\")\ndef health():\n    return {\"ok\": True}\n\n\n@app.post(\"/items\")\ndef create(item: Item):\n    item_id = len(items) + 1\n    items[item_id] = item.model_dump()\n    return {\"id\": item_id, **items[item_id]}\n\n\n@app.get(\"/items/{item_id}\")\ndef read(item_id: int):\n    if item_id not in items:\n        raise HTTPException(404, \"not found\")\n    return items[item_id]\n",
    "requirements.txt": "fastapi\nuvicorn\n", "README.md": README.replace("{run}", "pip install -r requirements.txt\nuvicorn main:app --reload"),
    ".gitignore": GITIGNORE_PY})
files("flask-app", "Code", "Flask web app", "One page with a template and a form.", "python flask web", {
    "app.py": "from flask import Flask, render_template, request\n\napp = Flask(__name__)\n\n\n@app.route(\"/\", methods=[\"GET\", \"POST\"])\ndef index():\n    name = request.form.get(\"name\", \"\")\n    return render_template(\"index.html\", name=name)\n\n\nif __name__ == \"__main__\":\n    app.run(debug=True)\n",
    "templates/index.html": "<!doctype html>\n<title>{{name}}</title>\n<form method=post><input name=name placeholder=\"Your name\"><button>Say hi</button></form>\n{% if name %}<p>Hi {{ name }}!</p>{% endif %}\n",
    "requirements.txt": "flask\n", "README.md": README.replace("{run}", "pip install -r requirements.txt\npython app.py"), ".gitignore": GITIGNORE_PY})
files("streamlit-dashboard", "Code", "Streamlit data dashboard", "Upload a CSV and chart it.", "python data dashboard streamlit", {
    "app.py": "import pandas as pd\nimport streamlit as st\n\nst.title(\"{{name}}\")\nfile = st.file_uploader(\"CSV file\", type=\"csv\")\nif file:\n    df = pd.read_csv(file)\n    st.dataframe(df)\n    column = st.selectbox(\"Chart column\", df.select_dtypes(\"number\").columns)\n    st.line_chart(df[column])\n",
    "requirements.txt": "streamlit\npandas\n", "README.md": README.replace("{run}", "streamlit run app.py")})
files("data-analysis", "Code", "Data analysis script", "Load, clean, summarise and plot a CSV.", "python data pandas analysis", {
    "analyze.py": "import sys\n\nimport pandas as pd\n\n\ndef main(path: str) -> None:\n    df = pd.read_csv(path)\n    df = df.dropna(how=\"all\")\n    print(df.describe(include=\"all\").T)\n    print(df.head())\n\n\nif __name__ == \"__main__\":\n    main(sys.argv[1] if len(sys.argv) > 1 else \"data.csv\")\n",
    "requirements.txt": "pandas\n", "README.md": README.replace("{run}", "python analyze.py data.csv")})
files("pytest-suite", "Code", "pytest test suite", "Tests folder with fixtures and a parametrized test.", "python tests pytest", {
    "tests/conftest.py": "import pytest\n\n\n@pytest.fixture\ndef sample():\n    return [3, 1, 2]\n",
    "tests/test_example.py": "import pytest\n\n\ndef test_sorted(sample):\n    assert sorted(sample) == [1, 2, 3]\n\n\n@pytest.mark.parametrize(\"a,b,total\", [(1, 1, 2), (2, 3, 5)])\ndef test_add(a, b, total):\n    assert a + b == total\n",
    "pytest.ini": "[pytest]\ntestpaths = tests\n"})
files("node-express", "Code", "Node.js Express API", "Express server with JSON routes.", "javascript node express api backend", {
    "index.js": "const express = require(\"express\");\nconst app = express();\napp.use(express.json());\nconst items = [];\n\napp.get(\"/health\", (_req, res) => res.json({ ok: true }));\napp.get(\"/items\", (_req, res) => res.json(items));\napp.post(\"/items\", (req, res) => { items.push(req.body); res.status(201).json(req.body); });\n\napp.listen(3000, () => console.log(\"{{name}} on http://localhost:3000\"));\n",
    "package.json": "{\n  \"name\": \"{{name}}\",\n  \"version\": \"0.1.0\",\n  \"scripts\": { \"start\": \"node index.js\" },\n  \"dependencies\": { \"express\": \"^4.19.2\" }\n}\n",
    "README.md": README.replace("{run}", "npm install\nnpm start"), ".gitignore": GITIGNORE_NODE})
files("node-cli", "Code", "Node.js command-line tool", "A small CLI with a bin entry.", "javascript node cli", {
    "bin/cli.js": "#!/usr/bin/env node\nconst [, , name = \"world\"] = process.argv;\nconsole.log(`Hello, ${name}!`);\n",
    "package.json": "{\n  \"name\": \"{{name}}\",\n  \"version\": \"0.1.0\",\n  \"bin\": { \"{{name}}\": \"bin/cli.js\" }\n}\n", "README.md": README.replace("{run}", "node bin/cli.js you")})
files("react-vite-ts", "Code", "React + Vite + TypeScript", "A React app with a counter component.", "react typescript frontend vite web", {
    "index.html": "<!doctype html>\n<html><head><meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>{{name}}</title></head>\n<body><div id=\"root\"></div><script type=\"module\" src=\"/src/main.tsx\"></script></body></html>\n",
    "src/main.tsx": "import { StrictMode } from \"react\";\nimport { createRoot } from \"react-dom/client\";\nimport { App } from \"./App\";\n\ncreateRoot(document.getElementById(\"root\")!).render(<StrictMode><App /></StrictMode>);\n",
    "src/App.tsx": "import { useState } from \"react\";\n\nexport function App() {\n  const [count, setCount] = useState(0);\n  return (\n    <main style={{ fontFamily: \"system-ui\", padding: 32 }}>\n      <h1>{{name}}</h1>\n      <button onClick={() => setCount(count + 1)}>Clicked {count} times</button>\n    </main>\n  );\n}\n",
    "package.json": "{\n  \"name\": \"{{name}}\",\n  \"private\": true,\n  \"type\": \"module\",\n  \"scripts\": { \"dev\": \"vite\", \"build\": \"tsc -b && vite build\" },\n  \"dependencies\": { \"react\": \"^19.0.0\", \"react-dom\": \"^19.0.0\" },\n  \"devDependencies\": { \"@types/react\": \"^19.0.0\", \"@types/react-dom\": \"^19.0.0\", \"@vitejs/plugin-react\": \"^4.3.0\", \"typescript\": \"^5.6.0\", \"vite\": \"^6.0.0\" }\n}\n",
    "vite.config.ts": "import { defineConfig } from \"vite\";\nimport react from \"@vitejs/plugin-react\";\n\nexport default defineConfig({ plugins: [react()] });\n",
    "tsconfig.json": "{\n  \"compilerOptions\": { \"target\": \"ES2022\", \"module\": \"ESNext\", \"moduleResolution\": \"bundler\", \"jsx\": \"react-jsx\", \"strict\": true, \"noEmit\": true },\n  \"include\": [\"src\"]\n}\n",
    "README.md": README.replace("{run}", "npm install\nnpm run dev"), ".gitignore": GITIGNORE_NODE})
files("vue-vite", "Code", "Vue 3 + Vite", "A Vue single-file component app.", "vue frontend vite web", {
    "index.html": "<!doctype html>\n<html><head><meta charset=\"UTF-8\"><title>{{name}}</title></head><body><div id=\"app\"></div><script type=\"module\" src=\"/src/main.js\"></script></body></html>\n",
    "src/main.js": "import { createApp } from \"vue\";\nimport App from \"./App.vue\";\n\ncreateApp(App).mount(\"#app\");\n",
    "src/App.vue": "<script setup>\nimport { ref } from \"vue\";\nconst count = ref(0);\n</script>\n\n<template>\n  <h1>{{name}}</h1>\n  <button @click=\"count++\">Clicked {{ count }} times</button>\n</template>\n",
    "package.json": "{\n  \"name\": \"{{name}}\",\n  \"private\": true,\n  \"type\": \"module\",\n  \"scripts\": { \"dev\": \"vite\", \"build\": \"vite build\" },\n  \"dependencies\": { \"vue\": \"^3.5.0\" },\n  \"devDependencies\": { \"@vitejs/plugin-vue\": \"^5.1.0\", \"vite\": \"^6.0.0\" }\n}\n",
    "vite.config.js": "import { defineConfig } from \"vite\";\nimport vue from \"@vitejs/plugin-vue\";\n\nexport default defineConfig({ plugins: [vue()] });\n", ".gitignore": GITIGNORE_NODE})
files("svelte-vite", "Code", "Svelte + Vite", "A Svelte app with reactive state.", "svelte frontend vite web", {
    "index.html": "<!doctype html>\n<html><head><meta charset=\"UTF-8\"><title>{{name}}</title></head><body><div id=\"app\"></div><script type=\"module\" src=\"/src/main.js\"></script></body></html>\n",
    "src/main.js": "import { mount } from \"svelte\";\nimport App from \"./App.svelte\";\n\nmount(App, { target: document.getElementById(\"app\") });\n",
    "src/App.svelte": "<script>\n  let count = $state(0);\n</script>\n\n<h1>{{name}}</h1>\n<button onclick={() => count++}>Clicked {count} times</button>\n",
    "package.json": "{\n  \"name\": \"{{name}}\",\n  \"private\": true,\n  \"type\": \"module\",\n  \"scripts\": { \"dev\": \"vite\", \"build\": \"vite build\" },\n  \"devDependencies\": { \"@sveltejs/vite-plugin-svelte\": \"^5.0.0\", \"svelte\": \"^5.0.0\", \"vite\": \"^6.0.0\" }\n}\n",
    "vite.config.js": "import { defineConfig } from \"vite\";\nimport { svelte } from \"@sveltejs/vite-plugin-svelte\";\n\nexport default defineConfig({ plugins: [svelte()] });\n", ".gitignore": GITIGNORE_NODE})
files("nextjs-app", "Code", "Next.js app", "App-router Next.js with one page.", "react nextjs web frontend fullstack", {
    "app/page.tsx": "export default function Home() {\n  return <main style={{ padding: 32 }}><h1>{{name}}</h1><p>Edit app/page.tsx</p></main>;\n}\n",
    "app/layout.tsx": "export const metadata = { title: \"{{name}}\" };\n\nexport default function RootLayout({ children }: { children: React.ReactNode }) {\n  return <html lang=\"en\"><body>{children}</body></html>;\n}\n",
    "package.json": "{\n  \"name\": \"{{name}}\",\n  \"private\": true,\n  \"scripts\": { \"dev\": \"next dev\", \"build\": \"next build\", \"start\": \"next start\" },\n  \"dependencies\": { \"next\": \"^15.0.0\", \"react\": \"^19.0.0\", \"react-dom\": \"^19.0.0\" },\n  \"devDependencies\": { \"typescript\": \"^5.6.0\", \"@types/react\": \"^19.0.0\" }\n}\n", ".gitignore": GITIGNORE_NODE + ".next/\n"})
files("electron-app", "Code", "Electron desktop app", "A window that loads a local page.", "electron desktop javascript", {
    "main.js": "const { app, BrowserWindow } = require(\"electron\");\n\napp.whenReady().then(() => {\n  const win = new BrowserWindow({ width: 900, height: 600 });\n  win.loadFile(\"index.html\");\n});\napp.on(\"window-all-closed\", () => app.quit());\n",
    "index.html": "<!doctype html><title>{{name}}</title><h1>{{name}}</h1>\n",
    "package.json": "{\n  \"name\": \"{{name}}\",\n  \"main\": \"main.js\",\n  \"scripts\": { \"start\": \"electron .\" },\n  \"devDependencies\": { \"electron\": \"^33.0.0\" }\n}\n", ".gitignore": GITIGNORE_NODE})
files("chrome-extension", "Code", "Chrome extension (Manifest V3)", "A popup extension with a button.", "chrome extension browser javascript", {
    "manifest.json": "{\n  \"manifest_version\": 3,\n  \"name\": \"{{name}}\",\n  \"version\": \"0.1.0\",\n  \"action\": { \"default_popup\": \"popup.html\" },\n  \"permissions\": [\"storage\"]\n}\n",
    "popup.html": "<!doctype html><html><body style=\"width:220px;font-family:system-ui\"><h3>{{name}}</h3><button id=go>Count</button><p id=out>0</p><script src=popup.js></script></body></html>\n",
    "popup.js": "const out = document.getElementById(\"out\");\nchrome.storage.local.get({ n: 0 }, ({ n }) => (out.textContent = n));\ndocument.getElementById(\"go\").onclick = () => chrome.storage.local.get({ n: 0 }, ({ n }) => chrome.storage.local.set({ n: n + 1 }, () => (out.textContent = n + 1)));\n"})
files("discord-bot", "Code", "Discord bot (Python)", "Replies to !ping; the token comes from an env var.", "python discord bot", {
    "bot.py": "import os\n\nimport discord\n\nintents = discord.Intents.default()\nintents.message_content = True\nclient = discord.Client(intents=intents)\n\n\n@client.event\nasync def on_message(message):\n    if message.author == client.user:\n        return\n    if message.content == \"!ping\":\n        await message.channel.send(\"pong\")\n\n\nclient.run(os.environ[\"DISCORD_TOKEN\"])\n",
    "requirements.txt": "discord.py\n", "README.md": README.replace("{run}", "set DISCORD_TOKEN=... (never commit it)\npython bot.py"), ".gitignore": GITIGNORE_PY})
files("telegram-bot", "Code", "Telegram bot (Python)", "Echo bot; the token comes from an env var.", "python telegram bot", {
    "bot.py": "import os\n\nfrom telegram import Update\nfrom telegram.ext import Application, ContextTypes, MessageHandler, filters\n\n\nasync def echo(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:\n    await update.message.reply_text(update.message.text)\n\n\napp = Application.builder().token(os.environ[\"TELEGRAM_TOKEN\"]).build()\napp.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))\napp.run_polling()\n",
    "requirements.txt": "python-telegram-bot\n", ".gitignore": GITIGNORE_PY})
files("rust-cli", "Code", "Rust command-line tool", "cargo project with argument parsing.", "rust cli", {
    "Cargo.toml": "[package]\nname = \"{{name}}\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
    "src/main.rs": "fn main() {\n    let name = std::env::args().nth(1).unwrap_or_else(|| \"world\".into());\n    println!(\"Hello, {name}!\");\n}\n",
    ".gitignore": "target/\n"})
files("go-http", "Code", "Go HTTP server", "net/http server with a JSON handler.", "go golang api backend", {
    "go.mod": "module {{name}}\n\ngo 1.22\n",
    "main.go": "package main\n\nimport (\n\t\"encoding/json\"\n\t\"log\"\n\t\"net/http\"\n)\n\nfunc main() {\n\thttp.HandleFunc(\"/health\", func(w http.ResponseWriter, r *http.Request) {\n\t\tjson.NewEncoder(w).Encode(map[string]bool{\"ok\": true})\n\t})\n\tlog.Println(\"listening on :8080\")\n\tlog.Fatal(http.ListenAndServe(\":8080\", nil))\n}\n"})
files("java-maven", "Code", "Java (Maven)", "A Maven project with a main class.", "java maven", {
    "pom.xml": "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">\n  <modelVersion>4.0.0</modelVersion>\n  <groupId>app</groupId>\n  <artifactId>{{name}}</artifactId>\n  <version>0.1.0</version>\n  <properties><maven.compiler.release>21</maven.compiler.release></properties>\n</project>\n",
    "src/main/java/app/Main.java": "package app;\n\npublic class Main {\n    public static void main(String[] args) {\n        System.out.println(\"Hello from {{name}}\");\n    }\n}\n", ".gitignore": "target/\n"})
files("csharp-console", "Code", "C# console app", ".NET console project.", "csharp dotnet", {
    "{{name}}.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\">\n  <PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework><Nullable>enable</Nullable></PropertyGroup>\n</Project>\n",
    "Program.cs": "Console.WriteLine(\"Hello from {{name}}\");\n", ".gitignore": "bin/\nobj/\n"})
files("cpp-cmake", "Code", "C++ with CMake", "A CMake project with one executable.", "cpp c++ cmake", {
    "CMakeLists.txt": "cmake_minimum_required(VERSION 3.20)\nproject({{name}} CXX)\nset(CMAKE_CXX_STANDARD 20)\nadd_executable({{name}} src/main.cpp)\n",
    "src/main.cpp": "#include <iostream>\n\nint main() {\n    std::cout << \"Hello from {{name}}\\n\";\n}\n", ".gitignore": "build/\n"})
files("arduino-sketch", "Code", "Arduino sketch", "Blink with a serial log (pairs with the Build tab).", "arduino hardware electronics", {
    "{{name}}/{{name}}.ino": "const int LED = LED_BUILTIN;\n\nvoid setup() {\n  pinMode(LED, OUTPUT);\n  Serial.begin(9600);\n}\n\nvoid loop() {\n  digitalWrite(LED, HIGH);\n  delay(500);\n  digitalWrite(LED, LOW);\n  delay(500);\n  Serial.println(\"blink\");\n}\n"})
files("raspberry-pi-gpio", "Code", "Raspberry Pi GPIO (Python)", "Toggle a pin with gpiozero.", "raspberry pi hardware python", {
    "blink.py": "from signal import pause\n\nfrom gpiozero import LED\n\nled = LED(17)\nled.blink(on_time=0.5, off_time=0.5)\npause()\n"})
files("godot-script", "Code", "Godot player script", "GDScript movement for a CharacterBody2D.", "godot game gdscript", {
    "player.gd": "extends CharacterBody2D\n\n@export var speed := 220.0\n\nfunc _physics_process(_delta: float) -> void:\n\tvar direction := Input.get_vector(\"ui_left\", \"ui_right\", \"ui_up\", \"ui_down\")\n\tvelocity = direction * speed\n\tmove_and_slide()\n"})
files("unity-script", "Code", "Unity player script", "C# MonoBehaviour movement.", "unity game csharp", {
    "PlayerController.cs": "using UnityEngine;\n\npublic class PlayerController : MonoBehaviour\n{\n    public float speed = 5f;\n\n    void Update()\n    {\n        var move = new Vector3(Input.GetAxis(\"Horizontal\"), 0, Input.GetAxis(\"Vertical\"));\n        transform.Translate(move * speed * Time.deltaTime);\n    }\n}\n"})
files("powershell-script", "Code", "PowerShell script", "A script with parameters and help.", "powershell windows script", {
    "{{name}}.ps1": "<#\n.SYNOPSIS\n  What {{name}} does.\n#>\nparam([string]$Name = \"world\")\n\nWrite-Output \"Hello, $Name!\"\n"})
files("bash-script", "Code", "Bash script", "A safe bash script skeleton.", "bash shell linux script", {
    "{{name}}.sh": "#!/usr/bin/env bash\nset -euo pipefail\n\nname=\"${1:-world}\"\necho \"Hello, ${name}!\"\n"})
files("sql-schema", "Code", "SQL schema", "Tables with keys, an index and a seed row.", "sql database schema", {
    "schema.sql": "CREATE TABLE users (\n  id INTEGER PRIMARY KEY,\n  email TEXT NOT NULL UNIQUE,\n  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n);\n\nCREATE TABLE orders (\n  id INTEGER PRIMARY KEY,\n  user_id INTEGER NOT NULL REFERENCES users(id),\n  total_cents INTEGER NOT NULL CHECK (total_cents >= 0),\n  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n);\n\nCREATE INDEX idx_orders_user ON orders(user_id);\n\nINSERT INTO users (email) VALUES ('owner@example.com');\n"})

# --- websites -----------------------------------------------------------------------------------

BASE_CSS = ("*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#1d1d1f;"
            "background:#fafafa;line-height:1.55}main,header,footer,section{max-width:1040px;margin:auto;padding:24px}"
            "a{color:#0066cc}.btn{display:inline-block;padding:12px 20px;border-radius:12px;background:#1d1d1f;color:#fff;"
            "text-decoration:none}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}"
            ".card{background:#fff;border-radius:16px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}"
            "@media (prefers-color-scheme:dark){body{background:#000;color:#f5f5f7}.card{background:#1c1c1e}.btn{background:#f5f5f7;color:#000}}\n")


def site(tid: str, title: str, description: str, tags: str, body: str) -> None:
    html = ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            "content=\"width=device-width, initial-scale=1\"><title>{{name}}</title><link rel=\"stylesheet\" href=\"style.css\">"
            "</head>\n<body>\n" + body.strip() + "\n</body></html>\n")
    files(tid, "Websites", title, description, "website html css " + tags,
          {"index.html": html, "style.css": BASE_CSS, "README.md": "# {{name}}\n\nOpen index.html in a browser.\n"})


site("landing-page", "Landing page", "Hero, features, call to action.", "landing marketing",
     "<header><h1>{{name}}</h1><p>One line about why it matters.</p><a class=btn href=#start>Get started</a></header>\n"
     "<section class=grid><div class=card><h3>Fast</h3><p>Why.</p></div><div class=card><h3>Simple</h3><p>Why.</p></div>"
     "<div class=card><h3>Private</h3><p>Why.</p></div></section>\n<footer id=start><a class=btn href=#>Sign up</a></footer>")
site("portfolio", "Portfolio", "About, projects grid, contact.", "portfolio personal",
     "<header><h1>{{name}}</h1><p>Designer · Developer</p></header>\n<main><h2>Projects</h2><div class=grid>"
     "<article class=card><h3>Project one</h3><p>What it was and what you did.</p></article>"
     "<article class=card><h3>Project two</h3><p>What it was and what you did.</p></article></div>"
     "<h2>Contact</h2><p><a href=\"mailto:you@example.com\">you@example.com</a></p></main>")
site("blog", "Blog", "Post list and a post layout.", "blog writing",
     "<header><h1>{{name}}</h1></header>\n<main><article class=card><h2>First post</h2><p><time>2026-01-01</time></p>"
     "<p>Write something worth reading.</p></article></main>")
site("docs-site", "Documentation site", "Sidebar navigation and content.", "docs documentation",
     "<main style=\"display:grid;grid-template-columns:220px 1fr;gap:24px\"><nav><h3>{{name}}</h3><ul><li><a href=#intro>Introduction"
     "</a></li><li><a href=#install>Install</a></li><li><a href=#use>Usage</a></li></ul></nav><article><h1 id=intro>Introduction"
     "</h1><p>What this is.</p><h2 id=install>Install</h2><pre><code>pip install {{name}}</code></pre><h2 id=use>Usage</h2>"
     "<p>Examples.</p></article></main>")
site("dashboard", "Dashboard", "KPI cards and a table.", "dashboard admin analytics",
     "<header><h1>{{name}}</h1></header>\n<main><section class=grid><div class=card><p>Revenue</p><h2>$12,400</h2></div>"
     "<div class=card><p>Users</p><h2>1,280</h2></div><div class=card><p>Churn</p><h2>2.1%</h2></div></section>"
     "<table class=card style=\"width:100%;margin-top:16px\"><tr><th align=left>Name</th><th align=left>Status</th></tr>"
     "<tr><td>Example</td><td>Active</td></tr></table></main>")
site("product-page", "Product page", "Gallery, details, buy button.", "shop ecommerce product",
     "<main class=grid><div class=card style=\"aspect-ratio:1\">Product photo</div><div><h1>{{name}}</h1><h2>$49</h2>"
     "<p>What it is, who it is for.</p><a class=btn href=#>Add to cart</a></div></main>")
site("pricing-page", "Pricing page", "Three plans side by side.", "pricing saas",
     "<header><h1>Pricing</h1></header>\n<main class=grid><div class=card><h3>Free</h3><h2>$0</h2></div><div class=card>"
     "<h3>Pro</h3><h2>$9/mo</h2></div><div class=card><h3>Team</h3><h2>$29/mo</h2></div></main>")
site("not-found-page", "404 page", "A friendly not-found page.", "404 error",
     "<main style=\"text-align:center;padding-top:15vh\"><h1 style=\"font-size:72px;margin:0\">404</h1><p>This page wandered off."
     "</p><a class=btn href=\"/\">Go home</a></main>")
site("link-in-bio", "Link in bio", "A single column of links.", "links social",
     "<main style=\"max-width:420px;text-align:center\"><h1>{{name}}</h1><p>A short bio.</p>"
     "<p><a class=btn href=#>My website</a></p><p><a class=btn href=#>Newsletter</a></p></main>")
files("email-newsletter", "Websites", "Email newsletter (HTML)", "Table-based email that renders in most mail apps.",
      "email newsletter html", {"newsletter.html": "<!doctype html><html><body style=\"margin:0;background:#f4f4f5\"><table width=100% "
      "cellpadding=0 cellspacing=0><tr><td align=center><table width=600 style=\"background:#fff;font-family:Arial,sans-serif\">"
      "<tr><td style=\"padding:24px\"><h1>{{name}}</h1><p>This month's news.</p><a href=# style=\"background:#111;color:#fff;"
      "padding:12px 18px;text-decoration:none;border-radius:6px\">Read more</a></td></tr></table></td></tr></table></body></html>\n"})

# --- devops -------------------------------------------------------------------------------------

files("dockerfile-python", "DevOps", "Dockerfile (Python)", "Slim Python image for a web app.", "docker container python", {
    "Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nCMD [\"python\", \"main.py\"]\n",
    ".dockerignore": ".venv\n__pycache__\n.git\n"})
files("docker-compose", "DevOps", "docker-compose (app + Postgres)", "An app and a database.", "docker compose postgres", {
    "compose.yaml": "services:\n  app:\n    build: .\n    ports: [\"8000:8000\"]\n    environment:\n      DATABASE_URL: postgresql://app:app@db:5432/app\n    depends_on: [db]\n  db:\n    image: postgres:16\n    environment:\n      POSTGRES_USER: app\n      POSTGRES_PASSWORD: app\n      POSTGRES_DB: app\n    volumes: [\"db:/var/lib/postgresql/data\"]\nvolumes:\n  db: {}\n"})
files("github-actions-python", "DevOps", "GitHub Actions: Python tests", "Run pytest on every push.", "ci github actions python", {
    ".github/workflows/tests.yml": "name: tests\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with: { python-version: \"3.12\" }\n      - run: pip install -r requirements.txt pytest\n      - run: pytest -q\n"})
files("github-actions-node", "DevOps", "GitHub Actions: Node build", "Install, build, test on push.", "ci github actions node", {
    ".github/workflows/build.yml": "name: build\non: [push, pull_request]\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-node@v4\n        with: { node-version: 22 }\n      - run: npm ci\n      - run: npm run build --if-present\n      - run: npm test --if-present\n"})
files("pre-commit", "DevOps", "pre-commit hooks", "Formatting and whitespace checks before each commit.", "git hooks lint", {
    ".pre-commit-config.yaml": "repos:\n  - repo: https://github.com/pre-commit/pre-commit-hooks\n    rev: v5.0.0\n    hooks:\n      - id: trailing-whitespace\n      - id: end-of-file-fixer\n      - id: check-yaml\n"})
files("gitignore-python", "DevOps", ".gitignore (Python)", "The usual Python ignores.", "git python", {".gitignore": GITIGNORE_PY})
files("gitignore-node", "DevOps", ".gitignore (Node)", "The usual Node ignores.", "git node", {".gitignore": GITIGNORE_NODE})

# --- documents ----------------------------------------------------------------------------------

doc("readme", "README", "Project README outline.", "readme docs", "# {{name}}\n\nOne sentence about what it does.\n\n## Install\n\n## Use\n\n## How it works\n\n## License")
doc("adr", "Architecture decision record", "ADR: context, decision, options, consequences.", "adr architecture", "# ADR-001: {{name}}\n\n**Status:** Proposed\n**Date:**\n\n## Context\n\n## Decision\n\n## Options considered\n\n## Consequences\n")
doc("prd", "Product requirements (PRD)", "Problem, goals, non-goals, requirements, metrics.", "prd product spec", "# {{name}} — PRD\n\n## Problem\n\n## Goals\n\n## Non-goals\n\n## Users\n\n## Requirements\n\n## Success metrics\n\n## Open questions")
doc("runbook", "Runbook", "How to operate and recover a service.", "runbook ops", "# {{name}} runbook\n\n## What it is\n\n## Health checks\n\n## Common alerts and fixes\n\n## Rollback\n\n## Contacts")
doc("resume", "Resume", "One-page resume layout.", "resume cv job", "# Your Name\nemail · phone · city · link\n\n## Experience\n**Role — Company** (dates)\n- Result with a number\n\n## Education\n\n## Skills")
doc("cover-letter", "Cover letter", "Short, specific cover letter.", "cover letter job", "Dear Hiring Manager,\n\nI'm applying for {{name}} because …\n\nIn my last role I …\n\nI'd love to talk about how I can help.\n\nSincerely,\n")
doc("meeting-notes", "Meeting notes", "Agenda, decisions, action items.", "meeting notes", "# {{name}} — meeting notes\n\n**Date:**  **People:**\n\n## Agenda\n\n## Decisions\n\n## Action items\n- [ ] who — what — when")
doc("lesson-plan", "Lesson plan", "Objective, activities, assessment.", "lesson teaching school", "# Lesson: {{name}}\n\n## Objective\n\n## Materials\n\n## Warm-up (5 min)\n\n## Activity (25 min)\n\n## Check for understanding\n\n## Homework")
doc("business-plan", "Business plan (one page)", "Problem, solution, market, money.", "business startup plan", "# {{name}} — one-page plan\n\n## Problem\n\n## Solution\n\n## Customers\n\n## Market size\n\n## Revenue model\n\n## Costs\n\n## Next 90 days")
doc("weekly-report", "Weekly status report", "Done, next, blocked.", "status report weekly", "# {{name}} — week of …\n\n## Done\n\n## Next\n\n## Blocked / risks")
doc("study-guide", "Study guide", "Key ideas, definitions, practice questions.", "study school exam", "# {{name}} study guide\n\n## Key ideas\n\n## Definitions\n\n## Worked example\n\n## Practice questions\n1.\n2.\n\n## Answers")

# --- tabs (validated dynamic tab specs) ---------------------------------------------------------

tab("tab-habit-tracker", "Habits", "Log daily habits and see streaks.", "habit tracker daily", "ph-check-circle", [
    {"type": "tracker", "title": "Workout", "config": {"kind": "yes_no"}},
    {"type": "tracker", "title": "Reading (pages)", "config": {"unit": "pages", "goal": 20}},
    {"type": "checklist", "title": "Today", "config": {}}])
tab("tab-budget", "Budget", "Track spending against a monthly goal.", "budget money finance", "ph-wallet", [
    {"type": "tracker", "title": "Spent today", "config": {"unit": "$", "goal": 50}},
    {"type": "chart", "title": "This month", "config": {}},
    {"type": "notes", "title": "Big expenses coming up", "config": {}}])
tab("tab-study-planner", "Study planner", "Focus timer, tasks and a study helper.", "study school planner", "ph-graduation-cap", [
    {"type": "timer", "title": "Focus", "config": {"mode": "pomodoro", "minutes": 25}},
    {"type": "checklist", "title": "Topics to cover", "config": {}},
    {"type": "chat", "title": "Ask about the material", "config": {}}])
tab("tab-kanban", "Board", "To do, doing, done.", "kanban tasks project", "ph-kanban", [
    {"type": "checklist", "title": "To do", "config": {}}, {"type": "checklist", "title": "Doing", "config": {}},
    {"type": "checklist", "title": "Done", "config": {}}])
tab("tab-reading-list", "Reading list", "Books and articles to read.", "reading books", "ph-books", [
    {"type": "checklist", "title": "To read", "config": {}}, {"type": "notes", "title": "Notes and quotes", "config": {}}])
tab("tab-workout-log", "Workout log", "Log sets and track progress.", "fitness workout gym", "ph-barbell", [
    {"type": "tracker", "title": "Bench press (kg)", "config": {"unit": "kg"}},
    {"type": "tracker", "title": "Run (km)", "config": {"unit": "km"}},
    {"type": "timer", "title": "Rest", "config": {"mode": "countdown", "minutes": 2}}])
tab("tab-recipe-box", "Recipes", "Save recipes and plan meals.", "recipes cooking food", "ph-cooking-pot", [
    {"type": "notes", "title": "Recipes", "config": {}}, {"type": "checklist", "title": "Shopping list", "config": {}},
    {"type": "chat", "title": "What can I cook with…", "config": {}}])
tab("tab-trip-planner", "Trip planner", "Itinerary, packing and bookings.", "travel trip vacation", "ph-airplane-tilt", [
    {"type": "notes", "title": "Itinerary", "config": {}}, {"type": "checklist", "title": "Packing", "config": {}},
    {"type": "links", "title": "Bookings", "config": {}}])
tab("tab-research-board", "Research board", "Questions, sources and findings.", "research study", "ph-magnifying-glass", [
    {"type": "checklist", "title": "Questions", "config": {}}, {"type": "links", "title": "Sources", "config": {}},
    {"type": "notes", "title": "Findings", "config": {}}, {"type": "chat", "title": "Ask Nyx", "config": {}}])
tab("tab-pomodoro", "Focus", "A pomodoro timer and a distraction list.", "focus pomodoro productivity", "ph-timer", [
    {"type": "timer", "title": "Pomodoro", "config": {"mode": "pomodoro", "minutes": 25}},
    {"type": "notes", "title": "Parked thoughts", "config": {}}])
tab("tab-stock-watch", "Stock watch", "Watch prices and log notes (paper only).", "stocks trading finance", "ph-chart-line-up", [
    {"type": "tracker", "title": "Portfolio value", "config": {"unit": "$"}},
    {"type": "notes", "title": "Ideas", "config": {}},
    {"type": "ai_task", "title": "Morning market brief", "config": {"prompt": "Give me a short market brief for today.", "every_minutes": 0}}])

# --- prompts ------------------------------------------------------------------------------------

prompt("prompt-code-review", "Code review", "code review", "Review this code for bugs, security problems and unclear parts. List each issue with the line, why it matters and a fix. Say what is good too.\n\n```\n(paste code)\n```")
prompt("prompt-explain", "Explain simply", "explain learn", "Explain {{name}} to me like I'm new to it: one plain sentence first, then an example, then the common mistakes.")
prompt("prompt-debug", "Debug helper", "debug error", "I get this error. Tell me the most likely cause, how to confirm it, and the smallest fix.\n\nError:\n(paste)\n\nCode:\n(paste)")
prompt("prompt-summarize", "Summarize", "summary", "Summarize this in 5 bullet points, then give the one thing I should remember.\n\n(paste text)")
prompt("prompt-translate", "Translate", "translate language", "Translate this into (language), keeping the tone and meaning. Point out anything that doesn't translate well.\n\n(paste text)")
prompt("prompt-quiz", "Quiz me", "study quiz", "Quiz me on {{name}}: 10 questions, one at a time, harder as I get them right. Tell me why after each answer.")

TEMPLATES: List[Dict[str, Any]] = T
