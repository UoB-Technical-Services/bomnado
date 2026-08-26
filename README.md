<div align="center" style="text-align:center; width: 100%">

# Bomnado 🌪️

**A Bill of Materials (BOM) management system for organising parts, assemblies, and manufacturing data**

</div>



<div align="center">

  [🏃‍➡️ Quick start](#quick-start)&emsp;
  [🛠️ Development](#development)&emsp;
  [🚀 Deployment](#deployment)&emsp;
  [✋ Contributing](#contributing)&emsp;
  [📃 License](#license)&emsp;

</div>

<div align="center">

  Built with ❤︎ by [HE Inventions](https://heinventions.com)

</div>

----

## Features

- **Parts management** - Track part specifications, suppliers, pricing, and inventory
- **Assembly hierarchy** - Build complex BOMs with nested subassemblies  
- **Team collaboration** - Multi-user access with team-based permissions
- **File attachments** - Support for images, documents, and CAD files
- **Export & reports** - Generate Excel spreadsheets and purchasing lists
- **REST API** - Full API access for integrations and automation
- **Search & filter** - Find parts and assemblies across your entire database

## AI assistant

Bomnado can work with an AI model (today: Claude, through your own Anthropic API key). Each user adds their
**own** key under *Settings -> AI assistant* (stored encrypted; never sent to the browser), picks a model, and
can set a monthly budget; the top bar shows how much of it is used.

**In the app** the AI is a chat window that floats over every page (the ✦ button in the top bar, or `Ctrl+K`).
It is movable and minimisable, follows you across pages and devices (conversations live on the server), and
knows which part or assembly you are looking at, so "make it black" or "find other suppliers for this" just
work. It can look things up, create and change parts and assemblies, read links and the files you drop in, and
search the web. Sparkle ✦ buttons next to fields are jumping-off points ("Draft QC steps", "Check this BOM for
gaps"). Everything it does is listed under the budget button.

**From Claude Desktop or Claude Code** the same tools are available as an MCP server - see below.

Both hosts see one tool surface (`bom/ai/tools.py`), the team's conventions and *reference naming guide*
(editable on the Teams page; fasteners follow `M8-20MM-BOLT-BTN-BZP` by default) as resources, and the same
jumping-off prompts.

The AI acts exactly as you would: every change goes through the same validation and team checks as the rest
of the app, is recorded in the history with a reason ("Chat: make it black - Bomnado AI") under your name,
and leaves an open "requires human review" comment on the record - so the 👀 flag shows what still needs a
look, and any change can be reverted from the *Feedback and history* strip. There is no approval step before
it acts; reversibility is the safety net.

Set `BOMNADO_FERNET_KEY` (a Fernet key) in production so stored API keys survive a `SECRET_KEY` rotation. Chat
turns run as Celery tasks where a broker is configured, and in a background thread otherwise.

### The MCP server

[MCP](https://modelcontextprotocol.io) is the open protocol AI clients use to call tools in other programs.
Bomnado is an MCP server (`bom/ai/mcp_server.py`), so Claude Desktop, Claude Code or any other MCP client can
read and change your catalogue the same way the in-app chat does - and you can mix Bomnado with the other
tools that client has (your files, a browser, GitHub...).

**How it works.** The server runs as a Django management command that speaks MCP over stdin/stdout (the
*stdio* transport): the client starts the process when it needs it and keeps it for the session. Every call
acts as the user named on the command line, so history shows your name, the reason names the client
(`Claude (MCP) - Bomnado AI`), and the review comment is left exactly as from the chat. There is no network
listener and no token: the process only ever runs on a machine that already has the database and your
login, which is why it is a local-only arrangement for now (a remote, authenticated HTTP transport would be
the next step if the team wants it from other machines).

```powershell
pdm run python manage.py mcp --user alice              # act as alice, in the first team she is in
pdm run python manage.py mcp --user alice --team Makers
```

**Claude Code** - register it once, then Bomnado's tools are available in every session in that project:

```powershell
claude mcp add bomnado -- pdm run python manage.py mcp --user alice
claude mcp list                                         # check it connected
```

**Claude Desktop** - add it to `claude_desktop_config.json` (*Settings -> Developer -> Edit Config*), with
`cwd` pointing at the checkout so `manage.py` and `.env` are found:

```json
{
  "mcpServers": {
    "bomnado": {
      "command": "pdm",
      "args": ["run", "python", "manage.py", "mcp", "--user", "alice"],
      "cwd": "C:\\path\\to\\bomnado"
    }
  }
}
```

Restart the client; the ✦ / tools menu should list Bomnado. Then talk normally: "what do we buy M8 nuts
from?", "create a part from this link", "check the BOX assembly for missing fasteners", "attach this
datasheet to LOOM" (files the client can read are passed through).

**What it exposes** - defined once in `bom/ai/tools.py`, so the chat window and MCP clients never differ:

| Kind | Names | Notes |
|---|---|---|
| Read tools | `search_parts`, `get_part`, `search_assemblies`, `get_assembly`, `get_history`, `fetch_page`, `read_attachment` | Bounded (20 rows, 30k characters of a page); only your teams' records; `get_part` includes suppliers, named pieces, attachments, where it is used and open feedback |
| Write tools | `create_part`, `update_part`, `add_supplier`, `update_supplier`, `add_named_piece`, `create_assembly`, `update_assembly`, `set_line_item`, `add_feedback`, `attach_file`, `set_picture` | Only the fields given change; `update_*` never blanks anything; a blank supplier row is filled rather than duplicated; `set_line_item` with quantity 0 removes |
| Resources | `bomnado://conventions`, `bomnado://naming-guide`, `bomnado://team` | House rules (dimensions are `L x W x H` in mm, prices per unit ex VAT, QC steps as task lists), the team's naming guide with existing references to copy, the team's members and projects |
| Prompts | `create_part_from_link`, `create_parts_from_files`, `find_suppliers`, `draft_qc_steps`, `check_assembly` | The same jumping-off points as the ✦ buttons in the app |

Tool errors ("no part called X", "not saved: reference: ...") come back as results the model can read and
act on, never as crashes; anything it cannot do is refused by the same permission checks as the web app.
Web search is not a Bomnado tool - the in-app chat gets it from the model provider, and an MCP client brings
its own - so ask the client to search and then call `add_supplier` with what it found.

## Quick start

**Local evaluation** (requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)):

```powershell
# Launch with Docker
docker compose -f docker-compose.eval.yml up -d --build

# Open http://127.0.0.1:8000 and create your first user account
```

> **⚠️ Warning**: This uses default settings and should not be used in production.

## Development

### Prerequisites

- Python 3.12+
- [PDM](https://pdm-project.org/en/latest/) for dependency management

*Note: Development uses SQLite by default; production deployments prefer PostgreSQL.*

### Setup

```powershell
# Install dependencies
pdm install

# Set up environment
cp .env.example .env

# Generate secret key
pdm run ./generate_secret_key.py -o .env

# Start development server
pdm run manage runserver
```

Open http://127.0.0.1:8000 to access Bomnado.

### Development commands

```powershell
# Run database migrations (can be done via the browser during first run)
pdm run migrate

# Create superuser (can be done via the browser during first run)
pdm run manage createsuperuser

# Run tests
pdm run test

# Create demo data
pdm run manage createdemo

# Django shell
pdm run manage shell

# Collect static files
pdm run manage collectstatic
```

## Deployment

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for detailed configuration options.

## Contributing

Want to help improve Bomnado? See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development setup and contribution guidelines.

## License

This project is licensed under the MIT License - see the [`LICENSE`](LICENSE) file for details.

## Backups

Bomnado backs itself up with django-dbbackup into `backups/` next to the project (the `dbbackup`
storage in `bomnado/settings/base.py`). In production a nightly Celery beat task does it
(`BACKUP_TIME`, 05:00 by default). An administrator can also press **Back Up Now** in the user
menu: it writes a database dump and a media archive and keeps the newest few of each
(`DBBACKUP_CLEANUP_KEEP`, 7 by default).

### Restoring

1. Stop the server.
2. List what you have: `pdm run python manage.py listbackups`
3. Restore the newest database dump: `pdm run python manage.py dbrestore --uncompress --noinput`
   (add `-i <filename>` for a specific one).
4. Restore the media files: `pdm run python manage.py mediarestore --uncompress --replace --noinput`
5. Start the server and check a few records.

A restore overwrites the current database and media, so take a fresh backup first if the
current state matters.
