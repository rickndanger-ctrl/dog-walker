import yaml
import pytest

from dog_walker.forms import parse_form, read_markdown_brief
from dog_walker.workflow import WalkerError


def handler_form():
    return {
        "dog_walker": 1,
        "name": "Prepare release",
        "goal": "Prepare a release note",
        "constraints": ["Keep the change scoped"],
        "steps": [{
            "id": "write",
            "title": "Write the note",
            "prompt": "Create the requested release note.",
            "success_criteria": ["The note is present"],
            "checks": [],
        }],
    }


def test_plain_markdown_is_preserved_as_a_brief(tmp_path):
    source = tmp_path / "Planning Notes.md"
    text = "# Add search\n\nLet users find items by name.\n"
    source.write_text(text, encoding="utf-8")

    brief = read_markdown_brief(source)

    assert brief["kind"] == "brief"
    assert brief["source"] == str(source)
    assert brief["text"] == text
    assert brief["title"] == "Add search"
    assert brief["suggested_folder"] == "add-search"
    assert brief["form"] is None and brief["form_text"] is None


def test_invalid_yaml_fence_remains_a_plain_brief(tmp_path):
    source = tmp_path / "notes.md"
    text = "# Plan\n\n```yaml\nname: incomplete\n```\n"
    source.write_text(text, encoding="utf-8")

    brief = read_markdown_brief(source)

    assert brief["kind"] == "brief"
    assert brief["text"] == text


def test_valid_embedded_handler_form_is_recognized(tmp_path):
    source = tmp_path / "plan.md"
    form_text = yaml.safe_dump(handler_form(), sort_keys=False)
    assert parse_form(form_text) == handler_form()
    source.write_text(f"# Release planning\n\n```yaml\n{form_text}```\n", encoding="utf-8")

    brief = read_markdown_brief(source)

    assert brief["kind"] == "handler_form"
    assert brief["form"] == handler_form()
    assert brief["form_text"].strip() == form_text.strip()
    assert brief["title"] == "Release planning"


@pytest.mark.parametrize("suffix", [".txt", ".dogwalk", ""])
def test_only_markdown_files_are_accepted(tmp_path, suffix):
    source = tmp_path / f"brief{suffix}"
    source.write_text("# Brief", encoding="utf-8")
    with pytest.raises(WalkerError, match="Markdown"):
        read_markdown_brief(source)


def test_symlink_and_non_regular_files_are_rejected(tmp_path):
    target = tmp_path / "target.md"
    target.write_text("# Private", encoding="utf-8")
    link = tmp_path / "link.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(WalkerError, match="regular files"):
        read_markdown_brief(link)
    directory = tmp_path / "directory.md"
    directory.mkdir()
    with pytest.raises(WalkerError, match="regular files"):
        read_markdown_brief(directory)


def test_oversize_and_binary_files_are_rejected(tmp_path):
    oversize = tmp_path / "large.md"
    oversize.write_bytes(b"a" * (256 * 1024 + 1))
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"# brief\x00data")

    with pytest.raises(WalkerError, match="256 KB"):
        read_markdown_brief(oversize)
    with pytest.raises(WalkerError, match="UTF-8 text"):
        read_markdown_brief(binary)


def test_invalid_utf8_is_rejected(tmp_path):
    source = tmp_path / "invalid.md"
    source.write_bytes(b"\xff\xfe")
    with pytest.raises(WalkerError, match="UTF-8 text"):
        read_markdown_brief(source)
