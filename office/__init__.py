"""Office Space — a whole office of agents you can watch working (Plan Null N8).

The owner's words (``AI_HANDOFF/PROJECT_NULL.md`` § N8): *"In here it can range from 10 to hundreds of agents
depending on task and computer ability … each agent is represented … You can give a large task and watch as
they work … a pseudo hierarchy system where it goes from top manager, to smaller managers of different
infrastructure to a final team of agents … Multiple models (basically all of them) are used here and each agent
uses one … It fully remembers things from previous sessions."*

What lives where
----------------
``state.py``      the records — Office, Section, Agent, Task, Message, HireRequest, Job — and their JSON form.
``library.py``    the office files and folders on disk: create, rename, move, link work flows, open in Explorer.
``roles.py``      what kinds of agent exist, their colour, glyph and the domain each one thinks in.
``casting.py``    how many agents this computer can hold, and which model each agent gets (Big Kahuna's table).
``talk.py``       one model call for one agent, with per-provider limits, cleaning and JSON salvage.
``memory.py``     what an office remembers between sessions, and what a linked folder shares.
``targeting.py``  "optimizers of only these groups" → the actual agents, offline and instantly.
``gatekeeper.py`` the Hiring Board: the agent class that only exists when too many agents are being made.
``crit_think.py`` the skill it thinks with.
``officetools.py``the small, office-scoped tool set a worker may call (files inside the office, web, messages).
``engine.py``     the runtime: plan → staff → brief → work → review → wrap, pause, halt, and the live events.
``focus.py``      "run only this tab": pausing Nyx's background work and resuming it by itself afterwards.
``api.py``        the stable entry points other parts of Nyx (voice, chat) call.

Two hard rules, both learned the hard way in this repo:

* **Never ``data_path("office/…")``** — in a dev checkout ``DATA_DIR`` *is* the project folder, so that would
  write into this code package. Office files live under ``offices/`` (see ``library.ROOT_NAME``).
* **Nothing here executes model-written code.** A worker's tools write text files inside its own office folder,
  read them back, search the web and message other agents. That is the whole surface.
"""

from __future__ import annotations

NAME = "Office Space"
TAB_ID = "office"

#: An office is never smaller than a real team, and never bigger than the machine can hold.
MIN_AGENTS = 10
MAX_AGENTS = 400
MAX_SECTIONS = 24
MAX_AGENTS_PER_SECTION = 48

#: The owner: "If it seems that too many agents are being added or new types of agents are made (say 10 at this
#: point) add a agent … where requests are given to it … and it decides if it should be done."
NEW_TYPES_BEFORE_GATEKEEPER = 10
HIRES_PER_WINDOW_BEFORE_GATEKEEPER = 10
HIRE_WINDOW_SECONDS = 600

#: How much of an office stays in the office file itself; the rest goes to history.jsonl / work/_reports.
KEEP_CHAT = 400
KEEP_FEED = 600
KEEP_TASK_PREVIEW = 1500
#: The Output box (Update 1, U41) and the staffing record (U42) keep their last N in the office file.
KEEP_OUTPUTS = 100
KEEP_STAFFING = 200

VERSION = "1.0.0"
