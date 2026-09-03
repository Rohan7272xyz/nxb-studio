"""A library of roles, kept as markdown the operator can read and edit.

Rohan's design: a role written once should be offered back the next time, so
the library grows with use rather than being curated up front. "the more we
create the more we have to use in the future for future workflows."

WHY MARKDOWN FILES AND NOT A DATABASE. These are prose the operator writes for
a model to read, and prose belongs in a file he can open, diff, edit in his
own editor and copy to another machine. A persona locked inside a JSON blob or
a browser's localStorage is one he cannot grep, and this project already holds
that a rule binding a FILE is the kind that survives.

The name is the filename, so the library IS the directory listing.
"""

import os
import re
import time

DIRNAME = "personas"

#: Filesystem-safe, readable, and reversible enough to recognise. Names are
#: the operator's, so they are slugged rather than rejected.
def slug(name):
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name).strip()).strip("-.")
    return (out or "persona")[:80]


def directory(ledger):
    return os.path.join(os.path.dirname(ledger), DIRNAME)


def path_for(ledger, name):
    return os.path.join(directory(ledger), slug(name) + ".md")


def save(ledger, name, body):
    """Write one persona. Returns its record.

    The file carries the title as an H1 so it reads as a document on its own,
    away from this tool -- which is the point of choosing markdown.
    """
    name = " ".join(str(name).split())
    body = str(body).strip()
    if not name:
        raise ValueError("a persona needs a name")
    if not body:
        raise ValueError("a persona with no text is not a persona")
    os.makedirs(directory(ledger), exist_ok=True)
    path = path_for(ledger, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"# {name}\n\n{body}\n")
    return {"name": name, "file": path, "body": body,
            "saved_at": os.path.getmtime(path)}


def load_all(ledger):
    """Every persona, newest first. A malformed file is skipped, not fatal."""
    out = []
    try:
        names = os.listdir(directory(ledger))
    except OSError:
        return out
    for filename in names:
        if not filename.endswith(".md"):
            continue
        path = os.path.join(directory(ledger), filename)
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        lines = text.splitlines()
        title = (lines[0].lstrip("# ").strip()
                 if lines and lines[0].startswith("#")
                 else filename[:-3])
        body = "\n".join(lines[1:]).strip() if lines and \
            lines[0].startswith("#") else text.strip()
        out.append({"name": title, "file": path, "body": body,
                    "saved_at": stamp})
    out.sort(key=lambda p: p["saved_at"], reverse=True)
    return out


def delete(ledger, name):
    try:
        os.remove(path_for(ledger, name))
    except OSError:
        return False
    return True


def matches(ledger, body):
    """The persona whose text equals `body`, or None.

    Used to decide whether to OFFER saving: prompting to save something
    already in the library is noise, and noise is how a prompt gets dismissed
    without being read.
    """
    wanted = " ".join(str(body).split())
    for persona in load_all(ledger):
        if " ".join(persona["body"].split()) == wanted:
            return persona
    return None
