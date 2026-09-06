# How to Talk to Nyx Pulse

Your AI assistant is ready. Here are all the ways to interact:

## **Quickest: One-Shot Chat**

```bash
# Ask a question and get an instant answer
python quick_chat.py "What is Python?"
python quick_chat.py "How do I use async?" --attribute coding
python quick_chat.py "Help me debug this" --attribute debugging
```

## **Fast: CLI One-Shot Mode**

```bash
# Use the CLI but exit after answering
python cli.py "Tell me about machine learning"
python cli.py --attribute explain "What is recursion?"
python cli.py --attribute web_development "Best practices for APIs?"
```

## **Interactive: Full Chat Loop**

```bash
# Start interactive conversation
python cli.py

# Or with an attribute
python cli.py --attribute coding
```

Once in interactive mode, use these commands:
- `/help` — Show available commands
- `/attribute coding` — Switch to coding mode mid-conversation
- `/remember favorite_tool=Ollama` — Store your preferences
- `/memory` — View saved preferences
- `/history` — Show conversation
- `/status` — System status
- `/clear` — Clear history
- `/quit` — Exit

## **Windows Shortcut: Batch Launcher**

```bash
# Double-click chat.bat or use from cmd/PowerShell
chat.bat "your question here"
```

## **Attributes** (Change Response Style)

Apply any of these to shift how the assistant responds:

- `coding` — Code-focused with examples and tests
- `web_development` — Web-specific patterns and frameworks
- `app_development` — Mobile and desktop app guidance
- `debugging` — Deep diagnostic and troubleshooting
- `explain` — Educational, simple explanations
- `auto_model` — Default smart mode

## **Example Workflows**

### Quick Debug Session
```bash
python cli.py --attribute debugging "Why does this fail?"
python quick_chat.py "What's the error trace mean?" --attribute debugging
```

### Learning & Coding
```bash
python cli.py --attribute coding
> /remember learning_style=examples_first
> How do I write async code?
> /quit
```

### Multi-question Session
```bash
python cli.py --attribute web_development
> What REST best practices should I follow?
> /remember preferred_framework=FastAPI
> How do I handle auth?
> /quit
```

## **Personal Memory**

Once you set preferences, they persist across sessions:

```bash
python cli.py
> /remember work_style=step_by_step
> /remember favorite_language=Python
> /remember response_style=concise
```

The model will remember these and adjust its responses accordingly.

## **System Requirements**

- Python 3.9+
- Ollama running locally on port 11434 (default)
- `llama3.1` model (or configure in `.env`)

## **Get Help**

```bash
python cli.py --help
python quick_chat.py --help
```

---

**Ready?** Just type: `python quick_chat.py "your question"`
