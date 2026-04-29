#!/usr/bin/env python3
"""Preview how ``ImportStats v1.js`` will interpret a statblock text file.

The Roll20 script in this repository does not parse a statblock in a generic
way. It depends on a very specific sequence of cleanup rules, keyword matches,
and section-splitting heuristics. This Python script exists to make that
behavior visible from the command line so a text file can be debugged locally
before pasting it into Roll20.

Design goals:
- stay dependency-free so the script can run in a fresh clone with `python3`
- preserve the quirks of the JavaScript importer where possible
- show both successful imports and likely failure modes
- report the intermediate structures that explain *why* the importer behaved
  the way it did

The output is intentionally diagnostic rather than pretty. It is meant to help
you answer questions like:
- Which section headers did the parser detect?
- Did a trait get misclassified as an action?
- Which attributes would be written to the target NPC sheet?
- Which repeating actions/traits would the script attempt to create?

This script uses only the Python standard library, so the repository currently
does not need the virtualenv/bootstrap logic described in the user request.
If a future version adds third-party dependencies and a `requirements.txt`
file, that bootstrap behavior should be added at process start.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any


SKILL_ABILITY = {
    "acrobatics": "dexterity",
    "animal handling": "wisdom",
    "arcana": "intelligence",
    "athletics": "strength",
    "deception": "charisma",
    "history": "intelligence",
    "insight": "wisdom",
    "intimidation": "charisma",
    "investigation": "intelligence",
    "medicine": "wisdom",
    "nature": "intelligence",
    "perception": "wisdom",
    "performance": "charisma",
    "persuasion": "charisma",
    "religion": "intelligence",
    "sleight of hand": "dexterity",
    "stealth": "dexterity",
    "survival": "wisdom",
}

STANDARD_KEYWORDS = re.compile(
    r"#\s*(tiny|small|medium|large|huge|gargantuan|armor class|hit points|speed|str|dex|con|int|wis|cha|saving throws|skills|damage resistances|damage immunities|condition immunities|damage vulnerabilities|senses|languages|challenge|traits|actions|bonus actions|legendary actions|reactions)(?=\s|#)",
    re.IGNORECASE,
)
POWER_RE = re.compile(
    r"(?:#|\.\s+)([A-Z][\w-]+(?:\s(?:[A-Z][\w-]+|[\(\)\d/-]|of)+)*)(?=\s*\.)"
)


class ImportPreview:
    """Mirror the key parsing stages of ``ImportStats v1.js``.

    The original script mixes three responsibilities:
    - normalize the raw GM notes text
    - detect sections and sub-sections by regex
    - convert those sections into Roll20 attribute writes

    This helper class keeps those stages explicit so the final report can show
    the same categories the JavaScript code effectively works with.
    """

    def __init__(self) -> None:
        """Initialize parser state for a single import preview run.

        Attributes are stored in insertion order so the printed report reads in
        roughly the same order the JavaScript importer would create/update them.
        """
        self.errors: list[str] = []
        self.attributes: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self.character_name: str | None = None

    def set_attribute(self, name: str, current: Any, max_value: Any = "") -> None:
        """Record a would-be Roll20 attribute write.

        The JS importer silently logs and skips attempts to write an undefined
        value. This method mirrors that behavior by recording an error instead
        of throwing.
        """
        if current is None:
            self.errors.append(f"Error setting empty value: {name}")
            return
        self.attributes[name] = {"current": current, "max": max_value}

    def capitalize_each_word(self, text: str) -> str:
        """Match the JS title-casing used when naming the Roll20 character."""
        return re.sub(r"\w\S*", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), text)

    def clean(self, statblock: str) -> str:
        """Normalize the raw text into the JS importer's internal format.

        Important detail: the Roll20 script usually reads GM notes that contain
        HTML line breaks. Local text files do not, so this preview first maps
        real newlines to `#`, the same separator token the JS cleanup phase
        uses after converting `<br>` tags.
        """
        text = html.unescape(statblock)
        text = text.replace("–", "-")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("\n", "#")
        text = re.sub(r"<br[^>]*>", "#", text, flags=re.IGNORECASE)
        text = re.sub(r"(<([^>]+)>)", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+#\s+", "#", text)
        text = re.sub(r"#(?=[a-z])", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text

    def find_keyword(self, statblock: str) -> dict[str, OrderedDict[str, int]]:
        """Locate the parser's recognized headers and ability names.

        The JS importer does not truly parse a grammar. Instead, it finds the
        byte offsets of known keywords and later slices the text according to
        those offsets. That means a missing header, abbreviated label, or
        period in the wrong place can radically change how later text is
        classified.
        """
        keyword: dict[str, OrderedDict[str, int]] = {
            "attr": OrderedDict(),
            "traits": OrderedDict(),
            "actions": OrderedDict(),
            "bonusactions": OrderedDict(),
            "legendary": OrderedDict(),
            "reactions": OrderedDict(),
        }

        index_action = 0
        index_legendary = len(statblock)
        index_reactions = len(statblock)
        index_bonus = len(statblock)

        for match in STANDARD_KEYWORDS.finditer(statblock):
            key = match.group(1).lower()
            if key == "actions":
                index_action = match.start()
                keyword["actions"]["Actions"] = match.start()
            elif key == "legendary actions":
                index_legendary = match.start()
                keyword["legendary"]["Legendary"] = match.start()
            elif key == "bonus actions":
                index_bonus = match.start()
                keyword["bonusactions"]["BonusActions"] = match.start()
            elif key == "reactions":
                index_reactions = match.start()
                keyword["reactions"]["ReActions"] = match.start()
            else:
                keyword["attr"][key] = match.start()

        for match in POWER_RE.finditer(statblock):
            power_name = match.group(1)
            if power_name.lower() in keyword["attr"]:
                continue
            idx = match.start()
            if idx < index_action:
                keyword["traits"][power_name] = idx
            elif idx < index_reactions:
                if idx < index_legendary:
                    if idx < index_bonus:
                        keyword["actions"][power_name] = idx
                    else:
                        keyword["bonusactions"][power_name] = idx
                else:
                    keyword["legendary"][power_name] = idx
            else:
                keyword["reactions"][power_name] = idx

        return keyword

    def extract_section(self, text: str, start: int, end: int, title: str) -> str:
        """Slice out a section body and remove its leading title marker.

        This mirrors the JS behavior of trimming the matched keyword or action
        name off the front of the extracted block before further parsing.
        """
        section = text[start:end]
        pattern = re.compile(
            r"^[\s\.\#]*" + re.escape(title).replace(r"\-", "-") + r"?[\s\.\#]*",
            re.IGNORECASE,
        )
        section = pattern.sub("", section)
        return section.replace("#", " ")

    def split_statblock(
        self, statblock: str, keyword: dict[str, OrderedDict[str, int]]
    ) -> dict[str, Any]:
        """Split the normalized statblock into named sections.

        This is the most fragile phase of the original importer. It walks the
        keyword offsets in discovery order and progressively assigns slices to:
        - top-level attributes
        - traits
        - actions
        - bonus actions
        - legendary actions
        - reactions

        It also applies several JS-specific post-processing steps:
        - collapse the six ability entries into one `abilities` field
        - rewrite the size/type/alignment line into a `size` field
        - move certain summary blocks back into `traits`
        """
        bio = None
        pos = statblock.find("###")
        if pos != -1:
            bio = re.sub(r"^[#\s]", "", statblock[pos + 3 :])
            bio = bio.replace("#", "<br>").strip()
            statblock = statblock[:pos]

        start = 0
        key_name = "name"
        section_name = "attr"

        for section, obj in list(keyword.items()):
            if not isinstance(obj, OrderedDict):
                continue
            for key, end in list(obj.items()):
                keyword[section_name][key_name] = self.extract_section(statblock, start, end, key_name)
                key_name = key
                start = end
                section_name = section
        keyword[section_name][key_name] = self.extract_section(statblock, start, len(statblock), key_name)

        keyword["actions"].pop("Actions", None)
        keyword["legendary"].pop("Legendary", None)
        keyword["reactions"].pop("ReActions", None)
        keyword["bonusactions"].pop("BonusActions", None)

        if bio is not None:
            keyword["bio"] = bio

        abilities_name = ["str", "dex", "con", "int", "wis", "cha"]
        abilities = ""
        for ability in abilities_name:
            if ability in keyword["attr"]:
                abilities += f"{keyword['attr'][ability]} "
                del keyword["attr"][ability]
        keyword["attr"]["abilities"] = abilities

        sizes = ["tiny", "small", "medium", "large", "huge", "gargantuan"]
        for size in sizes:
            if size in keyword["attr"]:
                keyword["attr"]["size"] = f"{size} {keyword['attr'][size]}"
                del keyword["attr"][size]
                break

        if "Legendary Actions" in keyword["legendary"]:
            keyword["traits"]["Legendary Actions"] = keyword["legendary"].pop("Legendary Actions")
        if "Bonus Actions" in keyword["bonusactions"]:
            keyword["traits"]["Bonus Actions"] = keyword["bonusactions"].pop("Bonus Actions")
        if "Reactions" in keyword["reactions"]:
            keyword["traits"]["Reactions"] = keyword["reactions"].pop("Reactions")

        return keyword

    def parse_abilities(self, abilities: str) -> None:
        """Extract the six core ability scores from the combined abilities field."""
        matches = re.findall(r"(\d+)\s*\(", abilities)
        names = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
        for idx, name in enumerate(names):
            value = matches[idx] if idx < len(matches) else None
            self.set_attribute(name, value)
            self.set_attribute(f"{name}_base", value)

    def parse_size(self, size: str) -> None:
        """Parse the `Size type, alignment` line.

        The JS importer writes `npc_type` twice, with the second write replacing
        the extracted creature type with the whole size line. This preview
        mirrors that behavior so the output matches the existing script rather
        than an idealized version of it.
        """
        match = re.match(r"(.*?) (.*?), (.*)", size, flags=re.IGNORECASE)
        if not match:
            self.errors.append(f"Could not parse size/type/alignment: {size}")
            return
        self.set_attribute("npc_size", match.group(1))
        self.set_attribute("npc_type", match.group(2))
        self.set_attribute("npc_alignment", match.group(3))
        self.set_attribute("npc_type", size)

    def parse_armor_class(self, ac: str) -> None:
        """Parse the armor class line.

        If a parenthetical armor type exists, the JS importer strips the
        surrounding parentheses by substring position rather than by structured
        parsing. This method preserves that behavior.
        """
        match = re.match(r"(\d+)\s?(.*)", ac)
        if not match:
            self.errors.append(f"Could not parse armor class: {ac}")
            return
        self.set_attribute("npc_AC", match.group(1))
        ac_type = match.group(2)
        if len(ac_type) >= 2:
            self.set_attribute("npc_actype", ac_type[1:-1])

    def parse_hp(self, hp: str) -> None:
        """Parse hit points and derive the HP formula used by the sheet.

        The JS importer only reads the dice expression, then recomputes the
        Constitution bonus rather than trusting the trailing arithmetic in the
        source text. This preview does the same.
        """
        match = re.match(r".*?(\d+)\s+\(((?:\d+)d(?:\d+))", hp, flags=re.IGNORECASE)
        if not match:
            self.errors.append(f"Could not parse hit points: {hp}")
            return
        hp_value = match.group(1)
        self.set_attribute("hp", hp_value, hp_value)
        match2 = re.match(r"^(\d+)d(\d+)$", match.group(2))
        if not match2:
            self.errors.append(f"Could not parse hp formula dice: {hp}")
            return
        nb_dice = int(match2.group(1))
        con = self.attributes.get("constitution_base", {}).get("current")
        hp_bonus = (int(con) - 10) // 2 if con is not None else 0
        self.set_attribute("npc_hpformula", f"{match.group(2)}+{nb_dice * hp_bonus}")

    def parse_speed(self, speed: str) -> None:
        """Store speed text as-is."""
        self.set_attribute("npc_speed", speed)

    def parse_challenge(self, cr: str) -> None:
        """Parse challenge rating and XP from the challenge line."""
        compact = re.sub(r"[, ]", "", cr)
        match = re.match(r"([\d/]+).*?(\d+)", compact)
        if not match:
            self.errors.append(f"Could not parse challenge: {cr}")
            return
        self.set_attribute("npc_challenge", match.group(1))
        self.set_attribute("npc_xp", int(match.group(2)))

    def parse_saving_throw(self, save: str) -> None:
        """Parse saving throw bonuses.

        The JS importer stores both the printed total save and an adjusted
        bonus that accounts for the sheet recalculating ability modifiers.
        """
        attr_map = {
            "str": "strength",
            "dex": "dexterity",
            "con": "constitution",
            "int": "intelligence",
            "wis": "wisdom",
            "cha": "charisma",
        }
        for short, value in re.findall(r"(STR|DEX|CON|INT|WIS|CHA).*?(\d+)", save, flags=re.IGNORECASE):
            ability = attr_map[short.lower()]
            base = self.attributes.get(ability, {}).get("current")
            modifier = (int(base) - 10) // 2 if base is not None else 0
            self.set_attribute(f"{ability}_save_bonus", int(value) - modifier)
            self.set_attribute(f"npc_{short.lower()}_save_base", value)
            self.set_attribute(f"npc_{short.lower()}_save_flag", 1)
            self.set_attribute("npc_saving_flag", 1)

    def parse_skills(self, skills: str) -> None:
        """Parse skill bonuses into the sheet's expected NPC skill fields."""
        self.set_attribute("npc_skills_flag", 1)
        skill_text = re.sub(r"Skills\s+", "", skills, flags=re.IGNORECASE)
        for skill_name, value in re.findall(r"([\w\s]+).*?(\d+)", skill_text, flags=re.IGNORECASE):
            skill = skill_name.strip().lower()
            if skill in SKILL_ABILITY:
                attr = f"npc_{skill.replace(' ', '')}_base"
                attr_flag = f"npc_{skill.replace(' ', '')}_flag"
                self.set_attribute(attr, value)
                self.set_attribute(attr_flag, 1)
            else:
                self.errors.append(f"Skill {skill} is not a valid skill")

    def parse_senses(self, senses: str) -> None:
        """Store the senses line as-is."""
        self.set_attribute("npc_senses", senses)

    def parse_attack(self, value: str) -> dict[str, str]:
        """Approximate the JS attack parser for repeating NPC actions.

        This intentionally mirrors the original script's quirks, including its
        loose detection of `Hit:` lines and its simplistic damage extraction.
        The goal is not to improve it, but to show what the existing importer
        is likely to produce.
        """
        attack = {
            "attack_type": "",
            "attack_range": "",
            "to_hit": "",
            "target": "",
            "damage": "",
            "damage_type": "",
            "damage2": "",
            "damage2_type": "",
            "description": "",
        }
        hit_check = re.search(r"[hit]\:", value)
        if hit_check and hit_check.start() > 0:
            attack["attack_type"] = "Ranged"
            if re.search(r"Melee", value):
                attack["attack_type"] = "Melee"
                start = re.search(r"reach ", value, flags=re.IGNORECASE)
                end = re.search(r" ft", value, flags=re.IGNORECASE)
                if start and end:
                    attack["attack_range"] = value[start.start() : end.start() + 3].replace("reach", "").strip()
            else:
                start = re.search(r"range ", value, flags=re.IGNORECASE)
                end = re.search(r" ft", value, flags=re.IGNORECASE)
                if start and end:
                    attack["attack_range"] = value[start.start() : end.start() + 3].replace("range", "").strip()

            start = re.search(r"attack:", value, flags=re.IGNORECASE)
            end = re.search(r"to hit", value, flags=re.IGNORECASE)
            if start and end:
                attack["to_hit"] = value[start.end() : end.start()].strip()

            target_start = re.search(r"[.][,]", value, flags=re.IGNORECASE)
            target_end = re.search(r"[hit]\:", value, flags=re.IGNORECASE)
            if target_start and target_end:
                attack["target"] = value[target_start.start() + 3 : target_end.start() - 3].strip()

            damage_pos = value.find("damage")
            if damage_pos != -1:
                attack["description"] = value[damage_pos + 7 :].strip()
        else:
            attack["description"] = value
            attack["attack_type"] = "Ranged"

        damage_matches = re.findall(r"(\d+)?d(\d+)([\+\-]\d+)?", re.sub(r"\s+", "", value), flags=re.IGNORECASE)
        dtype_matches = re.findall(r"\)(.{1,15})damage", value)
        if damage_matches:
            attack["damage"] = "".join(part for part in damage_matches[0] if part)
        if dtype_matches:
            attack["damage_type"] = dtype_matches[0][1:].strip()

        if len(dtype_matches) > 1:
            if len(dtype_matches) > 2:
                if re.search(r"hands", value):
                    if len(damage_matches) > 2:
                        attack["damage2"] = "".join(part for part in damage_matches[2] if part)
                    attack["damage2_type"] = dtype_matches[2][1:].strip()
                    hit_match = re.search(r"[hit]\:", value, flags=re.IGNORECASE)
                    if hit_match:
                        attack["description"] = value[hit_match.end() :].strip()
            else:
                if len(damage_matches) > 1:
                    attack["damage2"] = "".join(part for part in damage_matches[1] if part)
                attack["damage2_type"] = dtype_matches[1][1:].strip()

        return attack

    def parse_traits(self, traits: OrderedDict[str, str]) -> list[dict[str, str]]:
        """Convert parsed trait blocks into repeating trait entries."""
        out = []
        for key, value in traits.items():
            out.append({"name": key, "description": re.sub(r"[\.\s]+$", ".", value)})
        return out

    def parse_actions(self, actions: OrderedDict[str, str]) -> list[dict[str, Any]]:
        """Convert parsed action blocks into repeating NPC action entries.

        As in the JS importer, any action text containing the word `damage` is
        treated as an attack action and routed through the attack parser.
        """
        out: list[dict[str, Any]] = []
        for key, value in actions.items():
            entry: dict[str, Any] = {"name": key}
            if "damage" in value:
                entry["attack_flag"] = "on"
                entry["attack"] = self.parse_attack(value)
            else:
                entry["attack_flag"] = "off"
                entry["description"] = re.sub(r"(\+\s?(\d+))", r"\1 : [[1d20+\2]]|[[1d20+\2]]", value)
            out.append(entry)
        return out

    def parse_legendary_actions(self, actions: OrderedDict[str, str]) -> tuple[int | None, list[dict[str, Any]]]:
        """Convert legendary actions and emulate the default count behavior.

        The JS importer assumes 3 legendary actions if at least one legendary
        entry exists, regardless of any summary text that may say otherwise.
        """
        out: list[dict[str, Any]] = []
        count = 0
        for key, value in actions.items():
            count += 1
            entry: dict[str, Any] = {"name": key}
            if "damage" in value and value.find("damage") > 0:
                entry["attack_flag"] = "on"
                entry["attack"] = self.parse_attack(value)
            else:
                entry["attack_flag"] = "off"
                entry["description"] = value
            out.append(entry)
        return (3 if count else None, out)

    def parse_reactions(self, reactions: OrderedDict[str, str]) -> list[dict[str, str]]:
        """Convert reactions into repeating reaction entries."""
        return [{"name": key, "description": value} for key, value in reactions.items()]

    def parse_bonus_actions(self, actions: OrderedDict[str, str]) -> list[dict[str, str]]:
        """Convert bonus actions into repeating bonus action entries."""
        return [{"name": key, "description": value} for key, value in actions.items()]

    def process_section(self, section: dict[str, Any]) -> dict[str, Any]:
        """Apply field-specific parsing to the split section data.

        This corresponds to the JS `processSection()` path for a newly-created
        character rather than the update path that only adds traits/reactions.
        """
        attr = section["attr"]
        if "abilities" in attr:
            self.parse_abilities(attr["abilities"])
        if "size" in attr:
            self.parse_size(attr["size"])
        if "armor class" in attr:
            self.parse_armor_class(attr["armor class"])
        if "hit points" in attr:
            self.parse_hp(attr["hit points"])
        if "speed" in attr:
            self.parse_speed(attr["speed"])
        if "challenge" in attr:
            self.parse_challenge(attr["challenge"])
        if "saving throws" in attr:
            self.parse_saving_throw(attr["saving throws"])
        if "skills" in attr:
            self.parse_skills(attr["skills"])
        if "senses" in attr:
            self.parse_senses(attr["senses"])

        if "damage immunities" in attr:
            self.set_attribute("npc_immunities", attr["damage immunities"])
        if "condition immunities" in attr:
            self.set_attribute("npc_condition_immunities", attr["condition immunities"])
        if "damage vulnerabilities" in attr:
            self.set_attribute("npc_vulnerabilities", attr["damage vulnerabilities"])
        if "languages" in attr:
            self.set_attribute("npc_languages", attr["languages"])
        if "damage resistances" in attr:
            self.set_attribute("npc_resistances", attr["damage resistances"])

        actions = self.parse_actions(section["actions"])
        legendary_count, legendary = self.parse_legendary_actions(section["legendary"])
        if legendary_count is not None:
            self.set_attribute("npc_legendary_actions", legendary_count)
        bonus = self.parse_bonus_actions(section["bonusactions"])
        if bonus:
            self.set_attribute("npcbonusactionsflag", 1)

        result = {
            "traits": self.parse_traits(section["traits"]),
            "actions": actions,
            "bonus_actions": bonus,
            "legendary_actions": legendary,
            "reactions": self.parse_reactions(section["reactions"]),
        }
        if result["reactions"]:
            self.set_attribute("npcreactionsflag", 1)
        return result

    def parse_statblock(self, raw: str) -> dict[str, Any]:
        """Run the full preview pipeline and return a diagnostic structure.

        The returned dictionary is suitable for both human-readable reporting
        and the optional JSON output mode.
        """
        cleaned = self.clean(raw.strip())
        keyword = self.find_keyword(cleaned)
        section = self.split_statblock(cleaned, keyword)

        name = section["attr"].get("name", "").strip()
        if not name:
            raise ValueError("Could not determine creature name")
        self.character_name = self.capitalize_each_word(name)
        self.set_attribute("is_npc", 1)
        self.set_attribute("npc", 1)
        self.set_attribute("npc_name", self.character_name)
        self.set_attribute("npc_options-flag", 1)
        self.set_attribute("whispertoggle", "/w gm ")

        repeated = self.process_section(section)
        return {
            "character_name": self.character_name,
            "cleaned_statblock": cleaned,
            "sections": {
                "attr": dict(section["attr"]),
                "traits": dict(section["traits"]),
                "actions": dict(section["actions"]),
                "bonusactions": dict(section["bonusactions"]),
                "legendary": dict(section["legendary"]),
                "reactions": dict(section["reactions"]),
                "bio": section.get("bio"),
            },
            "attributes": self.attributes,
            "repeating": repeated,
            "errors": self.errors,
        }


def main(argv: list[str]) -> int:
    """Command-line entry point.

    Exit codes:
    - 0: parsed successfully with no recorded warnings/errors
    - 1: input file was missing
    - 2: unrecoverable parsing exception
    - 3: parse completed, but one or more import-like errors were recorded
    """
    parser = argparse.ArgumentParser(
        description="Preview how ImportStats v1.js will import a statblock text file."
    )
    parser.add_argument("input_file", nargs="?", default="import.txt", help="input text file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of a text report",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    raw = input_path.read_text(encoding="utf-8")
    preview = ImportPreview()
    try:
        result = preview.parse_statblock(raw)
    except Exception as exc:  # mirrors JS broad catch
        print(f"Parsing was incomplete due to error(s): {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if not result["errors"] else 3

    print(f"Character name: {result['character_name']}")
    print()
    print("Attributes:")
    for name, payload in result["attributes"].items():
        if payload["max"] != "":
            print(f"  {name}: current={payload['current']!r}, max={payload['max']!r}")
        else:
            print(f"  {name}: current={payload['current']!r}")

    print()
    print("Detected sections:")
    for section_name, payload in result["sections"].items():
        if section_name == "bio":
            if payload:
                print(f"  {section_name}: {payload!r}")
            continue
        print(f"  {section_name}: {len(payload)} item(s)")
        for key, value in payload.items():
            print(f"    {key}: {value}")

    print()
    print("Repeating entries:")
    for group_name, entries in result["repeating"].items():
        print(f"  {group_name}: {len(entries)} item(s)")
        for entry in entries:
            print(f"    {json.dumps(entry, ensure_ascii=True)}")

    if result["errors"]:
        print()
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error}")
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
