from notion_reader import _rich, _block_lines


def test_rich_text_with_link():
    rt = [{"plain_text": "сайт", "href": "https://x"},
          {"plain_text": " и текст", "href": None}]
    assert _rich(rt) == "[сайт](https://x) и текст"


def test_heading_renders_as_markdown():
    b = {"id": "1", "type": "heading_2", "has_children": False,
         "heading_2": {"rich_text": [{"plain_text": "Требования", "href": None}]}}
    assert _block_lines(b) == ["## Требования"]


def test_bulleted_item():
    b = {"id": "2", "type": "bulleted_list_item", "has_children": False,
         "bulleted_list_item": {"rich_text": [{"plain_text": "пункт", "href": None}]}}
    assert _block_lines(b) == ["- пункт"]


def test_unknown_block_skipped():
    b = {"id": "3", "type": "image", "has_children": False, "image": {}}
    assert _block_lines(b) == []
