"""
A reader for the slice of YAML that library.yml actually uses.

PyYAML is used whenever it is installed. This exists so the installer needs
nothing but Python. pip then has nothing to fetch besides the installer itself,
which is what lets its wheel be installed on a machine with no internet.

What is supported, which is everything the manifest format uses:

    key: value                  mappings
    nested:                     nested mappings, by indentation
      key: value
    list:                       block sequences
      - item
      - key: value              block sequences of mappings
        other: value
    flow: [a, b, c]             flow sequences, including the empty []
    # comments                  to end of line
    'quoted' and "quoted"       strings
    true false yes no null      the scalars PyYAML resolves the same way

What is not supported, because no manifest needs it: anchors and aliases,
multiple documents, block scalars (| and >), flow mappings, and complex keys.
Anything unsupported raises YamlError naming the line, rather than being guessed
at, because a wrong guess would be far worse than a refusal.
"""

import re

# A quoted scalar, so a "#" inside quotes is not mistaken for a comment.
_QUOTED = re.compile(r"""^(?P<quote>['"])(?P<body>.*)(?P=quote)$""")

_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}
_NULL = {"", "null", "~"}


class YamlError(Exception):
    """The document uses something this reader does not understand."""


class _Line:
    """One meaningful line, with its indentation measured."""

    def __init__(self, number, raw):
        self.number = number
        self.text = raw.strip()
        self.indent = len(raw) - len(raw.lstrip(" "))

    def __repr__(self):
        return f"_Line({self.number}, {self.indent}, {self.text!r})"


def _strip_comment(raw):
    """Remove a trailing comment, leaving one inside quotes alone."""
    out = []
    quote = None

    for char in raw:
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#":
            # A "#" only starts a comment when it follows whitespace or begins
            # the line, which is what keeps a value like "a#b" intact.
            if not out or out[-1] in " \t":
                break

        out.append(char)

    return "".join(out).rstrip()


def _clean(text):
    """Meaningful lines only, comments and blanks dropped."""
    lines = []

    for number, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError(f"line {number}: indented with a tab, which YAML forbids")

        stripped = _strip_comment(raw)

        if stripped.strip():
            lines.append(_Line(number, stripped))

    return lines


def _scalar(text):
    """Turn one scalar into a Python value, the way PyYAML would."""
    text = text.strip()

    quoted = _QUOTED.match(text)
    if quoted:
        return quoted.group("body")

    if text.startswith("[") and text.endswith("]"):
        return _flow_sequence(text)

    lowered = text.lower()

    if lowered in _NULL:
        return None
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False

    try:
        return int(text)
    except ValueError:
        pass

    try:
        return float(text)
    except ValueError:
        pass

    return text


def _flow_sequence(text):
    """A one line list: [a, b, c] or []."""
    inner = text[1:-1].strip()

    if not inner:
        return []

    if "[" in inner or "{" in inner:
        raise YamlError(f"nested flow collections are not supported: {text}")

    return [_scalar(part) for part in _split_flow(inner)]


def _split_flow(inner):
    """Split on commas that are not inside quotes."""
    parts = []
    current = []
    quote = None

    for char in inner:
        if quote:
            if char == quote:
                quote = None
            current.append(char)
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == ",":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)

    parts.append("".join(current))

    return [p.strip() for p in parts if p.strip()]


def _split_key(line):
    """Split "key: value" on the first colon that is not inside quotes."""
    quote = None

    for index, char in enumerate(line.text):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == ":":
            after = line.text[index + 1 :]
            if after and not after.startswith(" "):
                # "a:b" is a plain scalar in YAML, not a mapping.
                continue
            return line.text[:index].strip(), after.strip()

    return None, None


def _parse(lines, index, indent):
    """Parse one block at the given indentation. Returns (value, next index)."""
    if index >= len(lines):
        return None, index

    if lines[index].text.startswith("- "):
        return _parse_sequence(lines, index, indent)

    return _parse_mapping(lines, index, indent)


def _parse_mapping(lines, index, indent):
    result = {}

    while index < len(lines) and lines[index].indent == indent:
        line = lines[index]

        if line.text.startswith("- "):
            break

        key, value = _split_key(line)

        if key is None:
            raise YamlError(f"line {line.number}: expected 'key: value', found {line.text!r}")

        if value:
            result[key] = _scalar(value)
            index += 1
            continue

        # The value is a block on the following lines, or nothing at all.
        if index + 1 < len(lines) and lines[index + 1].indent > indent:
            result[key], index = _parse(lines, index + 1, lines[index + 1].indent)
        else:
            result[key] = None
            index += 1

    return result, index


def _parse_sequence(lines, index, indent):
    result = []

    while index < len(lines) and lines[index].indent == indent:
        line = lines[index]

        if not line.text.startswith("- "):
            break

        content = line.text[2:].strip()
        key, value = _split_key(_Line(line.number, content))

        if key is None:
            result.append(_scalar(content))
            index += 1
            continue

        # A mapping inside a sequence item. Rewriting the "- " as spaces turns
        # the item and its continuation lines into one ordinary block, which the
        # mapping parser already knows how to read.
        item_indent = indent + 2
        block = [_Line(line.number, content)]
        block[0].indent = item_indent

        index += 1
        while index < len(lines) and lines[index].indent >= item_indent:
            block.append(lines[index])
            index += 1

        value, consumed = _parse_mapping(block, 0, item_indent)

        if consumed != len(block):
            raise YamlError(f"line {block[consumed].number}: could not read this list item")

        result.append(value)

    return result, index


def parse(text):
    """
    Read a YAML document, preferring PyYAML when it is installed.

    Everything in this package goes through here rather than importing yaml
    directly, so there is one place that decides which reader is in use.
    """
    try:
        import yaml
    except ImportError:
        return loads(text)

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise YamlError(str(error)) from error


def loads(text):
    """
    Read a YAML document into Python values, without PyYAML.

    Raises YamlError on anything this reader does not handle.
    """
    lines = _clean(text)

    if not lines:
        return None

    if lines[0].indent != 0:
        raise YamlError(f"line {lines[0].number}: the document starts indented")

    value, index = _parse(lines, 0, 0)

    if index != len(lines):
        raise YamlError(
            f"line {lines[index].number}: unexpected indentation, {lines[index].text!r}"
        )

    return value
