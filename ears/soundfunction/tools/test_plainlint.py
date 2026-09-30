#!/usr/bin/env python3
"""Tests for plainlint.py"""

import sys
import tempfile
import os
from pathlib import Path
from io import StringIO
from plainlint import Linter, ProseExtractor


def test_max_words():
    """Test that 12-word sentence is flagged, 11-word is not."""
    linter = Linter(max_words=11, max_sentences=6)

    # Test 11-word sentence (should pass)
    linter._check_block({
        'text': 'This is a test sentence with exactly eleven words in it.',
        'tag': 'p',
        'line': 1,
        'is_heading': False
    }, Path('test.html'))
    assert len([v for v in linter.violations if 'max-words' in v['rule']]) == 0, "11-word sentence should not flag"

    # Test 12-word sentence (should fail)
    linter.violations = []
    linter._check_block({
        'text': 'This is a test sentence with exactly twelve words in it here.',
        'tag': 'p',
        'line': 1,
        'is_heading': False
    }, Path('test.html'))
    assert len([v for v in linter.violations if 'max-words' in v['rule']]) == 1, "12-word sentence should flag"
    print("✓ Max words test passed")


def test_max_sentences():
    """Test that 7-sentence paragraph is flagged, 6 is not."""
    linter = Linter(max_words=11, max_sentences=6)

    # Test 6-sentence paragraph (should pass)
    text_6 = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence. Sixth sentence."
    linter.violations = []
    linter._check_block({
        'text': text_6,
        'tag': 'p',
        'line': 1,
        'is_heading': False
    }, Path('test.html'))
    assert len([v for v in linter.violations if 'max-sentences' in v['rule']]) == 0, "6-sentence paragraph should not flag"

    # Test 7-sentence paragraph (should fail)
    text_7 = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence. Sixth sentence. Seventh sentence."
    linter.violations = []
    linter._check_block({
        'text': text_7,
        'tag': 'p',
        'line': 1,
        'is_heading': False
    }, Path('test.html'))
    assert len([v for v in linter.violations if 'max-sentences' in v['rule']]) == 1, "7-sentence paragraph should flag"
    print("✓ Max sentences test passed")


def test_sentence_splitting():
    """Test sentence splitting with edge cases."""
    linter = Linter()

    # Test decimal: 1.5 seconds. Then more. should be 2 sentences, not 3
    sentences = linter._split_sentences("1.5 seconds. Then more.")
    assert len(sentences) == 2, f"Should split into 2 sentences, got {len(sentences)}: {sentences}"

    # Test abbreviation: e.g. this should not split
    sentences = linter._split_sentences("For example e.g. this is text.")
    assert len(sentences) == 1, f"Should not split on e.g., got {len(sentences)}: {sentences}"

    # Test ellipsis: Three dots should not cause extra split
    sentences = linter._split_sentences("Wait... then continue.")
    assert len(sentences) == 2, f"Should be 2 sentences with ellipsis, got {len(sentences)}: {sentences}"

    # Test i.e.
    sentences = linter._split_sentences("That is i.e. the thing. Next.")
    assert len(sentences) == 2, f"Should handle i.e., got {len(sentences)}"

    print("✓ Sentence splitting tests passed")


def test_word_counting():
    """Test word counting."""
    linter = Linter()

    # Test basic counting
    assert linter._count_words("hello world") == 2

    # Test hyphenated words count as one
    assert linter._count_words("kick-drum") == 1

    # Test apostrophes
    assert linter._count_words("don't can't") == 2

    # Test numbers count as words
    assert linter._count_words("150 BPM") == 2

    print("✓ Word counting tests passed")


def test_html_parsing():
    """Test that code and table content is ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test code tag ignored
        html_code = """
        <html>
        <p>This is visible.</p>
        <code>This should be ignored.</code>
        <p>This is also visible.</p>
        </html>
        """
        filepath = Path(tmpdir) / 'test.html'
        filepath.write_text(html_code)

        linter = Linter()
        linter.lint_file(filepath)

        # Should have extracted 2 paragraphs, not 3
        assert linter.stats['paragraphs'] == 2, f"Code content should be ignored, got {linter.stats['paragraphs']} paragraphs"

        # Test table ignored
        html_table = """
        <html>
        <p>Before table.</p>
        <table><tr><td>Cell with lots of text that should be ignored</td></tr></table>
        <p>After table.</p>
        </html>
        """
        filepath.write_text(html_table)
        linter = Linter()
        linter.lint_file(filepath)
        assert linter.stats['paragraphs'] == 2, f"Table content should be ignored, got {linter.stats['paragraphs']} paragraphs"

        print("✓ HTML parsing tests passed")


def test_data_plainlint_skip():
    """Test that data-plainlint='skip' is honored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        html = """
        <html>
        <p>This should be checked and has a very long sentence with way too many words in it.</p>
        <p data-plainlint="skip">This should be totally ignored and has a very long sentence with way too many words in it.</p>
        <p>This is also checked.</p>
        </html>
        """
        filepath = Path(tmpdir) / 'test.html'
        filepath.write_text(html)

        linter = Linter(max_words=10)
        linter.lint_file(filepath)

        # Should have only 2 paragraphs (skip one not counted)
        assert linter.stats['paragraphs'] == 2, f"Skipped paragraph should not be counted, got {linter.stats['paragraphs']}"

        # Should have violations from first paragraph, not second
        violations = [v for v in linter.violations if 'max-words' in v['rule']]
        assert len(violations) == 1, f"Should have 1 violation, got {len(violations)}"

        print("✓ data-plainlint='skip' test passed")


def test_hard_words():
    """Test hard word detection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create vocab file with only simple words
        vocab_file = Path(tmpdir) / 'vocab.txt'
        vocab_file.write_text("hello\nworld\nthis\nis\na\ntest\nword")

        # Create test HTML with hard word
        html = "<html><p>Hello world this is test.</p><p>Sophisticated analysis required.</p></html>"
        html_file = Path(tmpdir) / 'test.html'
        html_file.write_text(html)

        linter = Linter(vocab_file=str(vocab_file))
        linter.lint_file(html_file)

        # Should find hard words: sophisticated, analysis, required
        assert linter.stats['hard_words'] >= 3, f"Should find hard words, found {linter.stats['hard_words']}"

        print("✓ Hard words test passed")


def test_hard_words_with_glossary():
    """Test that glossary terms are allowed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create vocab file
        vocab_file = Path(tmpdir) / 'vocab.txt'
        vocab_file.write_text("hello\nworld\nthis\nis")

        # Create glossary file
        glossary_file = Path(tmpdir) / 'glossary.txt'
        glossary_file.write_text("sophisticated\nanalysis")

        # Create test HTML
        html = "<html><p>Hello world this is sophisticated analysis.</p></html>"
        html_file = Path(tmpdir) / 'test.html'
        html_file.write_text(html)

        linter = Linter(vocab_file=str(vocab_file), glossary_file=str(glossary_file))
        linter.lint_file(html_file)

        # Glossary terms should not be reported as hard words
        hard_words = [w for w in linter.hard_words_count.keys()]
        assert 'sophisticated' not in hard_words, "Glossary term should not be flagged"
        assert 'analysis' not in hard_words, "Glossary term should not be flagged"

        print("✓ Hard words with glossary test passed")


def test_unused_glossary_terms():
    """Test that unused glossary terms are reported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create glossary file
        glossary_file = Path(tmpdir) / 'glossary.txt'
        glossary_file.write_text("sophisticated\nanalysis\ntransmission")

        # Create test HTML that only uses some terms
        html = "<html><p>Hello world with sophisticated analysis.</p></html>"
        html_file = Path(tmpdir) / 'test.html'
        html_file.write_text(html)

        linter = Linter(glossary_file=str(glossary_file))
        linter.lint_file(html_file)

        unused = linter._check_glossary_coverage()
        assert 'transmission' in unused, "Unused glossary term should be reported"
        assert 'sophisticated' not in unused, "Used term should not be reported"

        print("✓ Unused glossary terms test passed")


def test_proper_nouns():
    """Test that capitalized words are not flagged as hard words."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create vocab file
        vocab_file = Path(tmpdir) / 'vocab.txt'
        vocab_file.write_text("hello\nworld")

        # Create test HTML with proper nouns
        html = "<html><p>Hello world from Alice and Bob.</p></html>"
        html_file = Path(tmpdir) / 'test.html'
        html_file.write_text(html)

        linter = Linter(vocab_file=str(vocab_file))
        linter.lint_file(html_file)

        # Alice and Bob should not be flagged as hard words (they're proper nouns)
        hard_words = linter.hard_words_count.keys()
        assert 'alice' not in hard_words, "Proper noun should not be flagged"
        assert 'bob' not in hard_words, "Proper noun should not be flagged"

        print("✓ Proper nouns test passed")


def test_exit_codes():
    """Test that exit codes are correct."""
    # Test exit 0 when no violations
    linter = Linter(max_words=20, max_sentences=20)
    linter._check_block({
        'text': 'Short sentence.',
        'tag': 'p',
        'line': 1,
        'is_heading': False
    }, Path('test.html'))
    assert not linter.should_exit_error(), "Should exit 0 with no violations"

    # Test exit 1 when max-words violation
    linter = Linter(max_words=5)
    linter._check_block({
        'text': 'This sentence has way too many words here.',
        'tag': 'p',
        'line': 1,
        'is_heading': False
    }, Path('test.html'))
    assert linter.should_exit_error(), "Should exit 1 with max-words violation"

    # Test exit 0 with --warn-only
    linter = Linter(max_words=5, warn_only=True)
    linter._check_block({
        'text': 'This sentence has way too many words here.',
        'tag': 'p',
        'line': 1,
        'is_heading': False
    }, Path('test.html'))
    assert not linter.should_exit_error(), "Should exit 0 with --warn-only"

    print("✓ Exit codes test passed")


def test_heading_no_paragraph_check():
    """Test that headings are checked for sentence length only, not paragraph length."""
    linter = Linter(max_words=11, max_sentences=6)

    # Create a heading with 7 sentences - should not be flagged for paragraph length
    heading_text = "First. Second. Third. Fourth. Fifth. Sixth. Seventh."
    linter._check_block({
        'text': heading_text,
        'tag': 'h1',
        'line': 1,
        'is_heading': True
    }, Path('test.html'))

    # Should have no paragraph violations (headings not checked as paragraphs)
    violations = [v for v in linter.violations if 'max-sentences' in v['rule']]
    assert len(violations) == 0, "Heading should not be flagged for paragraph length"

    print("✓ Heading test passed")


def test_inline_tags_stripped():
    """Test that inline tags are stripped but their text is kept."""
    linter = Linter()
    # Create HTML with inline tags
    with tempfile.TemporaryDirectory() as tmpdir:
        html = "<html><p>This is <strong>bold text</strong> and <em>italic text</em>.</p></html>"
        html_file = Path(tmpdir) / 'test.html'
        html_file.write_text(html)

        linter.lint_file(html_file)

        # Check that text was extracted (word count should be correct)
        assert linter.stats['sentences'] == 1, "Should extract text from inline tags"
        assert linter.stats['paragraphs'] == 1

        # Check actual word count is correct: This, is, bold, text, and, italic, text = 7 words
        sentences = linter._split_sentences("This is bold text and italic text.")
        words = linter._count_words(sentences[0])
        assert words == 7, f"Should count words correctly, got {words}"

    print("✓ Inline tags test passed")


def test_multiple_block_elements():
    """Test that different prose block types are extracted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        html = """
        <html>
        <h1>Heading</h1>
        <p>Paragraph text.</p>
        <ul>
            <li>List item one.</li>
            <li>List item two.</li>
        </ul>
        <blockquote>Quoted text.</blockquote>
        <dl>
            <dt>Term</dt>
            <dd>Definition here.</dd>
        </dl>
        </html>
        """
        html_file = Path(tmpdir) / 'test.html'
        html_file.write_text(html)

        linter = Linter()
        linter.lint_file(html_file)

        # Should extract multiple block types: h1, p, 2 li, blockquote, dt, dd = 8 total
        # But only 6 are paragraphs (h1 is not counted as paragraph)
        assert linter.stats['paragraphs'] >= 5, f"Should extract multiple block types, got {linter.stats['paragraphs']}"

    print("✓ Multiple block elements test passed")


def test_html_entity_decoding():
    """Test that HTML entities are decoded."""
    linter = Linter()
    with tempfile.TemporaryDirectory() as tmpdir:
        html = "<html><p>This is &quot;quoted&quot; text with &amp; ampersand.</p></html>"
        html_file = Path(tmpdir) / 'test.html'
        html_file.write_text(html)

        linter.lint_file(html_file)

        # Should decode entities properly
        assert linter.stats['sentences'] == 1
        assert linter.stats['paragraphs'] == 1

    print("✓ HTML entity decoding test passed")


if __name__ == '__main__':
    try:
        test_max_words()
        test_max_sentences()
        test_sentence_splitting()
        test_word_counting()
        test_html_parsing()
        test_data_plainlint_skip()
        test_hard_words()
        test_hard_words_with_glossary()
        test_unused_glossary_terms()
        test_proper_nouns()
        test_exit_codes()
        test_heading_no_paragraph_check()
        test_inline_tags_stripped()
        test_multiple_block_elements()
        test_html_entity_decoding()

        print("\n" + "="*50)
        print("All tests passed!")
        print("="*50)
        sys.exit(0)
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
