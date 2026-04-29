# `preview_import.py`

## Purpose

`preview_import.py` is a local diagnostic tool for this repository's Roll20 importer, [`ImportStats v1.js`](./ImportStats%20v1.js).

The JavaScript importer is strict and format-sensitive. Small differences such as:

- using `AC` instead of `Armor Class`
- omitting an `Actions` header
- missing periods after trait or action names
- compressing multiple fields onto one line

can cause a statblock to import incorrectly.

This script lets you test a text file locally and see how the importer will classify and interpret it before you paste it into Roll20.

## Requirements

The script currently uses only the Python standard library.

You do not need:

- a virtual environment
- `requirements.txt`
- third-party Python packages

Run it with a normal `python3`.

## Usage

### Default input file

If you run the script with no arguments, it will read `import.txt` from the current directory.

```bash
python3 preview_import.py
```

### Specify an input file

```bash
python3 preview_import.py godfatherofassassins.txt
python3 preview_import.py example_format.txt
```

### JSON output

If you want machine-readable output instead of the text report:

```bash
python3 preview_import.py --json example_format.txt
```

## Exit Codes

- `0`: parse completed with no recorded import-style errors
- `1`: input file was not found
- `2`: an unrecoverable parsing exception occurred
- `3`: parse completed, but one or more likely import errors were detected

`3` is useful because it means the parser got far enough to show you what it did, but it also found something suspicious.

## What the Script Shows

The normal text output is divided into several sections.

### Character name

This is the name the importer would use when creating or updating the Roll20 character.

### Attributes

These are the NPC sheet attributes the importer would write, such as:

- `npc_AC`
- `hp`
- `npc_speed`
- `npc_languages`
- `npc_resistances`

This is the closest local approximation to the importer calling `setAttribut(...)`.

### Detected sections

This shows how the parser split the source text into:

- `attr`
- `traits`
- `actions`
- `bonusactions`
- `legendary`
- `reactions`

If something lands in the wrong section, that usually explains the import problem.

### Repeating entries

This shows the rows the importer would try to create for repeating sheet sections, such as:

- traits
- actions
- bonus actions
- legendary actions
- reactions

### Errors

These are problems that mirror the original importer's failure modes, such as:

- missing values
- unrecognized skills
- malformed HP or size lines

## How It Works

The script mirrors the structure of `ImportStats v1.js` rather than implementing a new parser from scratch.

### 1. Cleanup phase

The source text is normalized to match the format the Roll20 script expects internally.

Important details:

- HTML entities are unescaped
- en dashes are converted to hyphens
- local text newlines are converted to `#`
- `<br>` tags are also converted to `#`
- extra whitespace is collapsed

This is important because the JavaScript importer normally reads statblocks from GM notes, where line breaks often appear as HTML.

### 2. Keyword detection

The script scans for exact parser-recognized labels such as:

- `Armor Class`
- `Hit Points`
- `Speed`
- `Skills`
- `Challenge`
- `Actions`
- `Legendary Actions`
- `Reactions`

It also scans for title-like entries ending with a period so it can infer trait and action names.

### 3. Section splitting

The parser does not use a formal grammar. It records string offsets for the recognized keywords and slices the statblock according to those positions.

This is why formatting matters so much. If a key header is missing, later text can slide into the wrong section.

### 4. Field parsing

After splitting the text, the script parses specific fields into NPC sheet attributes:

- ability scores
- size/type/alignment
- armor class
- hit points and HP formula
- challenge rating and XP
- saving throws
- skills
- senses
- languages
- vulnerabilities, resistances, and immunities

### 5. Repeating section generation

The script then approximates the repeating sheet rows the importer would try to create:

- repeating traits
- repeating actions
- repeating bonus actions
- repeating legendary actions
- repeating reactions

For actions containing the word `damage`, it applies the same rough attack parsing logic used by the JavaScript importer.

## Important Limits

This script is intentionally a mirror of the current importer, not a corrected parser.

That means:

- it preserves some quirks and rough edges of the JavaScript logic
- it may report strange results if the original importer would also behave strangely
- it is best used as a debugging aid, not as a validator for perfect 5e formatting

Examples of importer quirks the script intentionally preserves:

- `npc_type` gets overwritten with the whole size/type/alignment line
- action parsing is triggered by the presence of the word `damage`
- legendary action count defaults to `3` if any legendary actions are present

## Typical Debugging Workflow

1. Save a candidate statblock as a `.txt` file.
2. Run `python3 preview_import.py your_file.txt`.
3. Check `Detected sections` first.
4. If sections are wrong, fix formatting before worrying about attribute values.
5. Check `Repeating entries` next to confirm traits/actions landed where expected.
6. Check `Errors` last for missing fields or malformed lines.

## Examples

```bash
python3 preview_import.py example_format.txt
python3 preview_import.py godfatherofassassins.txt
python3 preview_import.py --json example_format.txt
```

## File Location

The script lives at:

- [`preview_import.py`](./preview_import.py)

This README lives at:

- [`preview_import_README.md`](./preview_import_README.md)
