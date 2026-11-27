# Agent skills

Skills let an AI agent (any agent that reads `SKILL.md` skills, such as Claude Code) use RockTranslate
on its own: it installs the engine, runs it, and reads the results for you.

| Skill | What the agent can do | Price |
|---|---|---|
| [`extract-scientific-pdf`](extract-scientific-pdf/) | PDF or link → JSON elements with page and box, Markdown, RAG chunks, figures as PNG. Local, no API key. | **Free** (this folder) |
| `translate-scientific-pdf` | PDF → translated PDF with the exact layout, bilingual copy, glossary, cost estimate | Coming to skill marketplaces |
| `read-scientific-paper` | Questions answered with verbatim quotes and pages, section summaries, formula explanations | Coming to skill marketplaces |

## Install

Copy the skill folder into your agent's skills directory, for example:

```bash
# Claude Code: personal skills
cp -r skills/extract-scientific-pdf ~/.claude/skills/
```

Then just ask, for example: *"Extract the tables of https://arxiv.org/abs/1706.03762 as Markdown"*.
The first time, the skill runs `scripts/rt_setup.py`, which finds `rocktranslate` or installs it in a private
virtual environment (no change to your system Python) and checks the engine with `rocktranslate doctor`.

Requirements: Python 3.9+; on macOS, `brew install pdf2htmlex`.
