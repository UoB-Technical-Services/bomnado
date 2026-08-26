# UX improvement plan (`ux-improvement` branch)

Branched from `feature/phase-8b-mcp` at `204c8f5` without merging. The goal is the mockup: a stable
three-region layout, a clear information hierarchy, a readable part library, a neutral visual style,
and no full-page refreshes while working - on a phone as well as a desktop.

## Principles

- Server-rendered Django + htmx 2 + Bootstrap 4 stay. No SPA. "No refresh" means htmx swapping the
  main region (`hx-get … hx-select="#app_main" hx-push-url="true"`) and posting forms the same way,
  so the library's search/scroll and the docked AI drawer survive every navigation and save.
- Views and forms keep their contracts; the work is templates, CSS and a little JS. Each step leaves
  every page working, with tests and flake8 green, and is one commit.
- Restraint: one primary colour, neutral surfaces, a type scale, a spacing scale, consistent
  components. Emoji as UI is replaced by text and icons where it carries meaning.

## Layout

```
┌ top bar: brand · Dashboard · Assemblies · Parts ············ search · ✦ AI · 75% ▮▮ · avatar ┐
├──────────────┬───────────────────────────────────────────────┬────────────────────────────┤
│ library      │ main                                           │ drawer (AI / review)       │
│ search,      │ sticky header: breadcrumb, title, status,      │ docked; opened when        │
│ filters,     │   Discard · Save changes · "Unsaved changes"   │ needed; can pop out to     │
│ rows with    │ jump links: Overview Physical Spec Sourcing …  │ the floating window        │
│ statuses     │ sections as cards                              │                            │
└──────────────┴───────────────────────────────────────────────┴────────────────────────────┘
```

On small screens (< 992px) the library and the drawer are off-canvas panels toggled from the top
bar; main takes the width; the sticky header condenses to title + Save.

## Steps

1. **Shell and theme.** New `partial/app.html`: top bar, `.app-shell` grid with `#app_library`,
   `#app_main`, `#app_drawer`. Existing `content` / `content-left` / `content-right` blocks map onto
   the regions so every page renders unchanged. `theme.css`: no patterned background, system font at
   15px, neutral surfaces, blue primary, status badges, consistent cards/inputs. The AI chat docks
   into the drawer by default (pop-out keeps the floating window). Split.js goes.
2. **Part library.** Server-rendered list with htmx search (300ms), filter pills (All / Needs
   attention / Missing data), readable rows (thumbnail, reference, name, status), pagination,
   selected row. Statuses from data (`bom/status.py`): Needs attention = open feedback; Missing
   weight / dimensions / price / supplier / picture; else Complete. Replaces the DataTables table
   and the `/api/parts` fetch. An Assemblies tab lists assemblies (and the tree).
3. **Part editor.** Sticky header (breadcrumb, name, status, Discard / Save, unsaved indicator,
   Ctrl+S), jump links with scroll-spy, sections as cards: Overview (picture, reference, name,
   manufacturer, nature, sales code, HS code) · Physical (dimensions, weight, colour) · Specification
   (spec, named pieces, QC steps) · Sourcing (suppliers, deals, Find suppliers) · Documents
   (attachments) · Usage (used in) · History (feedback & history) · Lifecycle (EOL, deprecated).
   Save and part-to-part navigation via htmx swaps of `#app_main`; inline errors; dirty guard.
4. **Assembly editor.** Same header / jump links / sections (Overview, Bill of materials,
   Instructions, QC, Documents, Usage, History); tree in the library's Assemblies tab; CSV import
   under Bill of materials.
5. **Everything else and polish.** Dashboard, teams, settings, tools on the theme; AI drawer chips
   ("4 fields updated on this page"); mobile pass with Playwright screenshots (390 / 768 / 1280);
   remove dead CSS/JS (Split.js, DataTables, patterned assets).

## Open questions

- Library width: fixed 360px (mockup) or resizable? Starting fixed; a drag handle is cheap later.
- Picture placeholder and thumbnails: generate small thumbnails server-side for the library rows.
- Review panel in the drawer (mockup mentions "AI assistant or review panel"): the activity strip
  could move into the drawer as a second tab. Deferred to step 5.

## Conventions that came out of the review rounds

- **One frame.** Both editors extend `pages/editor_base.html`; a page supplies blocks (`editor_crumbs`,
  `editor_sections`, `editor_more`...) and never repeats the header, the form skeleton or the jump nav.
- **No inline JavaScript in pages.** A page names its behaviour with `data-page="..."` on the main region and
  puts everything the module needs in data attributes beside it (ids, URLs from `{% url %}`, static paths).
  The module lives in `bom/static/app/pages/` and registers as `Bomnado.pages[name] = { init(main) }`; the
  shell initialises it on load and after every htmx swap of `#app_main`. Buttons declare `data-action`;
  the module handles them with one delegated listener, so swapped fragments need no re-wiring.
- **One renderer for references.** `templatetags/utils.reference_html` (also `stylised_part` / `stylised_assembly`
  and the markdown filter) draws every reference: a tinted chip - slate for parts, blue for assemblies, monospace -
  then marks from `library.marks()`: a red dot (open feedback), an amber dot (missing data),
  struck through when deprecated, a small tag for a sale code or a PCB. Rows that already show a status pill
  carry no dots. The browser builds the same markup from `Bomnado.marks` (the component search). No boxes, no
  emoji.
- **Checks in a real browser.** Anything touching htmx swaps is verified in Chrome (the extension) or with
  Playwright before it is committed; the test suite covers the markup contracts (data attributes, blocks).

## The secondary pages

Everything that is not an editor - Teams, Settings, AI activity, the dashboard, the five tools and the pages
outside the app - uses one vocabulary, so the information is organised the same way everywhere:

- a **page head** (breadcrumb · title · one-line lead saying what the page is for), then
- a stack of **sections** (`.bn-section`): a head with the title on the left and either meta or actions on the
  right; **sub-headings** (`.bn-subhead`) inside; **lists** (`.bn-list`) for rows of records; **labelled forms**
  (`.bn-label` + `.bn-form-row` + `.bn-hint`) with the primary button at the right; `.bn-empty` when there is
  nothing; a quiet `×` (`.bn-remove`) to take a row away.
- Roles and kinds are `.bn-tag` (owner, member, project); problems are `.bn-status` pills; nothing is shown
  for "fine" - complete is silent, broken is noisy (`Status.quiet`).

What each page holds, in the order it matters:

| Page | Purpose | Sections, top to bottom |
| --- | --- | --- |
| Dashboard | Pick a project | Team projects (card per project: chip, name, Tools / Export / Open) · New project |
| Teams (`bn-narrow`) | Who is in which team, and the team's settings | One section per team: head (name · n projects · n members) → Members list (owner tagged, × to remove) → Add a member → Naming guide · New team |
| Settings (`bn-narrow`) | You | Account (names, email, username · Reset password / Save) · Access (your role, your teams, Manage teams) · AI assistant (spend & activity in the head; key, model, budget) |
| AI activity | What the AI did and spent | Lead + spend line · Running (with Stop) · Recent (Clear) |
| Tools (all five) | One question about one project | Breadcrumb is Dashboard / PROJECT / Tool; lead says the question; a count line; then tables or review cards. Production phases is a tick sheet (Assembled · QC · Recorded) with Docs / Print per assembly |
| Sign in, reset, 403, 404 | Outside the app | The top bar with the brand and one card: title, lead, form, one link |

The AI drawer on these pages is the same docked drawer as on the editors; a test (`test_shell.py`) parses every
page and checks the library, main region and drawer are all direct children of the shell, because one stray
closing tag is enough to drop the drawer under the page.
