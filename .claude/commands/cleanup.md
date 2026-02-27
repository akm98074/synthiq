Scan this repository for stale markdown files and dead code, then clean them up.

## Step 1 — Audit markdown files

Find every `.md` file in the repo:

```bash
find . -name "*.md" -not -path "*/node_modules/*" -not -path "*/.git/*"
```

For each file, assess:
- Is it boilerplate that was never updated (e.g. default Next.js README)?
- Does it describe features, APIs, or setup steps that no longer match the actual code?
- Is it empty or near-empty?

Mark each file as one of: **keep**, **rewrite**, or **delete**.

## Step 2 — Audit dead code

Search for common dead-code patterns:

```bash
# Commented-out code blocks (3+ consecutive commented lines)
grep -rn "^\s*#\s*.\{20,\}" --include="*.py" .
grep -rn "^\s*//\s*.\{20,\}" --include="*.ts" --include="*.tsx" .

# TODO / FIXME / HACK / XXX markers
grep -rn "TODO\|FIXME\|HACK\|XXX\|DEPRECATED" --include="*.py" --include="*.ts" --include="*.tsx" .

# Unused imports (Python)
grep -rn "^import \|^from .* import" --include="*.py" .

# console.log statements left in production code
grep -rn "console\.log" --include="*.ts" --include="*.tsx" . | grep -v "\.test\." | grep -v "__tests__"
```

Also look for:
- Files ending in `.old`, `.bak`, `.unused`, `.tmp`
- Empty `__init__.py` files that serve no purpose beyond the package marker (these are fine — skip them)
- Duplicate utility functions across files

## Step 3 — Produce a cleanup report

Before making any changes, output a structured report:

```
MARKDOWN FILES
==============
[path] → [action: keep | rewrite | delete] — [one-line reason]

DEAD CODE
=========
[file:line] → [type: commented-out | TODO | console.log | unused-import] — [snippet]

ORPHANED FILES
==============
[path] → [reason it appears unused]
```

## Step 4 — Apply fixes

Ask the user to confirm before destructive actions (file deletion). Then:

1. **Delete** confirmed stale `.md` files.
2. **Rewrite** outdated `.md` files to accurately reflect the current code (read the relevant source files first).
3. **Remove** dead code: commented-out blocks, stray `console.log` calls, confirmed unused imports.
4. **Resolve or document** each TODO/FIXME — either fix the issue inline or convert it to a GitHub issue and remove the inline comment.

For each change, prefer the `Edit` tool over full rewrites to minimise diff size.

## Step 5 — Summarise

After all changes are applied, output:
- Files deleted
- Files rewritten
- Dead code items removed
- TODOs converted to issues or resolved inline
