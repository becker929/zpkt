#!/usr/bin/env python3
"""
Plain-language linter for prose in HTML, Markdown, and text files.
Checks against rules for sentence length, paragraph length, and vocabulary complexity.
"""

import sys
import re
import argparse
from pathlib import Path
from html.parser import HTMLParser
from html import unescape
from collections import defaultdict


class ProseExtractor(HTMLParser):
    """Extract visible prose text from HTML, respecting skip rules."""

    PROSE_TAGS = {'p', 'li', 'figcaption', 'dt', 'dd', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
    SKIP_TAGS = {'script', 'style', 'code', 'pre', 'kbd', 'samp', 'audio', 'table'}
    INLINE_TAGS = {'a', 'em', 'strong', 'abbr', 'span', 'b', 'i'}

    def __init__(self):
        super().__init__()
        self.prose_blocks = []  # List of (text, tag, line_number, is_heading)
        self.current_text = []
        self.current_tag = None
        self.skip_depth = 0
        self.inline_depth = 0
        self.line_number = 1
        self.skip_current = False
        self.tag_stack = []
        self.skip_tag_stack = []  # Track which tags should skip

    def handle_starttag(self, tag, attrs):
        self.line_number += self.get_starttag_text().count('\n') if self.get_starttag_text() else 0

        # Check for data-plainlint="skip"
        if dict(attrs).get('data-plainlint') == 'skip':
            self.skip_depth += 1
            self.skip_tag_stack.append(tag)
            return

        if self.skip_depth > 0:
            return

        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            self.skip_tag_stack.append(tag)
            return

        if tag in self.PROSE_TAGS:
            self.tag_stack.append((self.current_text, self.current_tag, self.skip_current))
            self.current_text = []
            self.current_tag = tag
            self.skip_current = False
        elif tag in self.INLINE_TAGS:
            self.inline_depth += 1

    def handle_endtag(self, tag):
        # Check if this closes a skip tag
        if self.skip_tag_stack and self.skip_tag_stack[-1] == tag:
            self.skip_tag_stack.pop()
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return

        if tag in self.SKIP_TAGS:
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return

        if tag in self.INLINE_TAGS:
            if self.inline_depth > 0:
                self.inline_depth -= 1
            return

        if tag in self.PROSE_TAGS and tag == self.current_tag:
            text = ''.join(self.current_text).strip()
            if text:
                is_heading = tag.startswith('h')
                self.prose_blocks.append({
                    'text': text,
                    'tag': tag,
                    'line': self.line_number,
                    'is_heading': is_heading
                })
            if self.tag_stack:
                self.current_text, self.current_tag, self.skip_current = self.tag_stack.pop()
            else:
                self.current_text = []
                self.current_tag = None

    def handle_data(self, data):
        if self.skip_depth > 0:
            self.line_number += data.count('\n')
            return

        if self.current_tag or self.inline_depth > 0:
            self.current_text.append(data)

        self.line_number += data.count('\n')

    def handle_entityref(self, name):
        if self.skip_depth == 0 and (self.current_tag or self.inline_depth > 0):
            self.current_text.append(f'&{name};')

    def handle_charref(self, name):
        if self.skip_depth == 0 and (self.current_tag or self.inline_depth > 0):
            self.current_text.append(f'&#{name};')


class Linter:
    """Main linter class."""

    # Common abbreviations that should not trigger sentence splits
    ABBREVIATIONS = {
        'dr', 'mr', 'mrs', 'prof', 'sr', 'jr', 'st', 'vs', 'inc', 'ltd', 'co',
        'e.g', 'i.e', 'etc', 'am', 'pm', 'oz', 'in', 'ft', 'km', 'cm', 'mm', 'lb',
        'kg', 'sec', 'min', 'max', 'approx', 'pt', 'fig'
    }

    def __init__(self, max_words=11, max_sentences=6, vocab_file=None, glossary_file=None,
                 names_file=None, warn_only=False, require_glossary_section=False):
        self.max_words = max_words
        self.max_sentences = max_sentences
        self.warn_only = warn_only
        self.require_glossary_section = require_glossary_section
        self.vocab = self._load_wordlist(vocab_file) if vocab_file else None
        self.glossary = self._load_wordlist(glossary_file) if glossary_file else None
        self.names = self._load_wordlist(names_file) if names_file else None
        self.glossary_terms_found = set()
        self.hard_words_count = defaultdict(int)
        self.violations = []
        self.stats = {
            'paragraphs': 0,
            'sentences': 0,
            'longest_sentence_words': 0,
            'longest_paragraph_sentences': 0,
            'hard_words': 0
        }

    def _load_wordlist(self, filepath):
        """Load a word/glossary list from a file."""
        if not filepath or not Path(filepath).exists():
            return set()
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return {line.strip().lower() for line in f if line.strip()}
        except Exception as e:
            print(f"Warning: Could not load {filepath}: {e}", file=sys.stderr)
            return set()

    def _split_sentences(self, text):
        """Split text into sentences, handling abbreviations, decimals, ellipses."""
        # Remove leading/trailing whitespace
        text = text.strip()
        if not text:
            return []

        # Track positions of periods to skip during splitting
        skip_periods = set()

        # Mark ellipsis periods as non-boundaries (but only the first two of "...")
        # The third period CAN be a boundary if followed by space
        for match in re.finditer(r'\.{3,}', text):
            # For "...", only mark the first two periods as "not boundaries"
            # The third one can be a boundary
            for pos in range(match.start(), match.end() - 1):
                skip_periods.add(pos)

        # Mark abbreviation periods as non-boundaries
        # Use word boundaries to avoid matching abbreviations within words (e.g., "st" in "almost")
        for abbr in self.ABBREVIATIONS:
            pattern = r'\b' + re.escape(abbr) + r'\.'
            for match in re.finditer(pattern, text, re.IGNORECASE):
                skip_periods.add(match.end() - 1)  # Position of the period

        # Mark decimal periods as non-boundaries (digit.digit)
        for match in re.finditer(r'\d\.(?=\d)', text):
            skip_periods.add(match.start() + 1)

        # Split on sentence-ending punctuation followed by space or end
        # but skip positions we marked
        sentences = []
        current = []
        i = 0
        while i < len(text):
            current.append(text[i])
            # Check if this is a sentence boundary
            if text[i] in '.!?' and i not in skip_periods:
                # A closing quote or bracket may sit between the mark and the
                # space: he said "why?" Then... -- the quote belongs to the
                # sentence that just ended.
                j = i + 1
                while j < len(text) and text[j] in '"\'\u201d\u2019)':
                    current.append(text[j]); j += 1
                if j >= len(text) or text[j].isspace():
                    sentence = ''.join(current).strip()
                    if sentence and re.search(r'[a-zA-Z]', sentence):
                        sentences.append(sentence)
                    current = []
                    i = j - 1
            i += 1

        # Add remaining text as a sentence if non-empty
        if current:
            sentence = ''.join(current).strip()
            if sentence and re.search(r'[a-zA-Z]', sentence):
                sentences.append(sentence)

        return sentences

    def _count_words(self, text):
        """Count words in text (runs of letters/digits/apostrophes/hyphens)."""
        words = re.findall(r"[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*", text)
        return len(words)

    def _get_words(self, text):
        """Extract words from text."""
        words = re.findall(r"[a-zA-Z0-9]+(?:['-][a-zA-Z0-9]+)*", text)
        return words

    def _is_proper_noun(self, word):
        """Check if a word is likely a proper noun (capitalized mid-sentence)."""
        return word and word[0].isupper()

    def _check_hard_words(self, text):
        """Check for words not in vocabulary."""
        if not self.vocab:
            return []

        words = self._get_words(text)
        hard_words = []

        for idx, word in enumerate(words):
            word_lower = word.lower()

            # Skip numbers
            if word.isdigit():
                continue

            # Skip if in vocab
            if word_lower in self.vocab:
                continue

            # Skip if in glossary
            if self.glossary and word_lower in self.glossary:
                self.glossary_terms_found.add(word_lower)
                continue

            # Skip if in names list
            if self.names and word_lower in self.names:
                continue

            # Skip if proper noun (but not if it's the first word, which is always capitalized)
            if idx > 0 and self._is_proper_noun(word):
                continue

            hard_words.append(word)
            self.hard_words_count[word_lower] += 1
            self.stats['hard_words'] += 1

        return hard_words

    def _track_glossary_usage(self, text):
        """Track which glossary terms appear in text."""
        if not self.glossary:
            return

        words = self._get_words(text)
        for word in words:
            word_lower = word.lower()
            if word_lower in self.glossary:
                self.glossary_terms_found.add(word_lower)

    def _check_glossary_coverage(self):
        """Check for unused glossary terms."""
        if not self.glossary:
            return []

        unused = []
        for term in self.glossary:
            if term not in self.glossary_terms_found:
                unused.append(term)

        return unused

    def lint_file(self, filepath):
        """Lint a single file."""
        filepath = Path(filepath)

        if not filepath.exists():
            print(f"Error: File not found: {filepath}", file=sys.stderr)
            return False

        # Determine content type and extract text
        if filepath.suffix.lower() == '.html':
            text = self._extract_from_html(filepath)
        elif filepath.suffix.lower() == '.md':
            text = self._extract_from_markdown(filepath)
        else:
            # Plain text
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()

        # Parse into prose blocks
        prose_blocks = self._parse_prose(text, filepath.suffix.lower() == '.html')

        # Check each prose block
        for block in prose_blocks:
            self._check_block(block, filepath)

        return True

    def _extract_from_html(self, filepath):
        """Extract text from HTML file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    def _extract_from_markdown(self, filepath):
        """Extract text from Markdown file (treat as plain text with some preprocessing)."""
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    def _parse_prose(self, content, is_html):
        """Parse content into prose blocks."""
        if is_html:
            parser = ProseExtractor()
            try:
                parser.feed(content)
            except Exception:
                # Fallback if HTML is malformed
                pass
            return parser.prose_blocks
        else:
            # For markdown/text, split by double newlines
            blocks = []
            paragraphs = content.split('\n\n')
            line = 1
            for para in paragraphs:
                para = para.strip()
                if para:
                    blocks.append({
                        'text': para,
                        'tag': 'p',
                        'line': line,
                        'is_heading': False
                    })
                line += para.count('\n') + 2
            return blocks

    def _check_block(self, block, filepath):
        """Check a single prose block against rules."""
        text = block['text']
        text = unescape(text)  # Decode HTML entities

        # Split into sentences
        sentences = self._split_sentences(text)

        if not sentences:
            return

        # Check each sentence
        for i, sentence in enumerate(sentences):
            word_count = self._count_words(sentence)
            self.stats['sentences'] += 1

            if word_count > self.max_words and not block['is_heading']:
                self.violations.append({
                    'file': str(filepath),
                    'line': block['line'],
                    'rule': 'max-words',
                    'message': f"Sentence has {word_count} words (max {self.max_words})",
                    'text': sentence[:120]
                })

            # Update longest sentence
            self.stats['longest_sentence_words'] = max(
                self.stats['longest_sentence_words'], word_count
            )

            # Check for hard words
            hard_words = self._check_hard_words(sentence)

            # Track glossary term usage (independent of vocab checking)
            if self.glossary:
                self._track_glossary_usage(sentence)

        # Check paragraph length (only for actual paragraphs, not headings)
        if not block['is_heading']:
            self.stats['paragraphs'] += 1
            sentence_count = len(sentences)

            if sentence_count > self.max_sentences:
                self.violations.append({
                    'file': str(filepath),
                    'line': block['line'],
                    'rule': 'max-sentences',
                    'message': f"Paragraph has {sentence_count} sentences (max {self.max_sentences})",
                    'text': text[:120]
                })

            # Update longest paragraph
            self.stats['longest_paragraph_sentences'] = max(
                self.stats['longest_paragraph_sentences'], sentence_count
            )

    def report(self):
        """Print violations and summary."""
        # Print violations
        for v in self.violations:
            quoted = v['text'].replace('\n', ' ')
            print(f"{v['file']}:{v['line']}: {v['rule'].upper()}: {v['message']}")
            print(f"  > {quoted}")

        # Print summary
        print()
        print("Summary:")
        print(f"  Paragraphs checked: {self.stats['paragraphs']}")
        print(f"  Sentences checked: {self.stats['sentences']}")
        print(f"  Longest sentence: {self.stats['longest_sentence_words']} words")
        print(f"  Longest paragraph: {self.stats['longest_paragraph_sentences']} sentences")

        if self.vocab:
            hard_words = self.stats['hard_words']
            print(f"  Hard words found: {hard_words}")
            if hard_words > 0:
                # Show top 20 most frequent
                top_20 = sorted(self.hard_words_count.items(), key=lambda x: -x[1])[:20]
                print("  Top 20 hard words:")
                for word, count in top_20:
                    print(f"    {word}: {count}")

        # Check for unused glossary terms
        if self.glossary:
            unused = self._check_glossary_coverage()
            if unused:
                print(f"  Unused glossary terms: {len(unused)}")
                for term in sorted(unused)[:20]:
                    print(f"    {term}")

    def should_exit_error(self):
        """Determine exit code."""
        if self.warn_only:
            return False

        # Exit non-zero if any violations
        if self.violations:
            return True

        # Exit non-zero if hard words found (only if vocab was provided)
        if self.vocab and self.stats['hard_words'] > 0:
            return True

        return False


def main():
    parser = argparse.ArgumentParser(description='Plain-language linter for prose.')
    parser.add_argument('file', help='HTML, Markdown, or text file to check')
    parser.add_argument('--max-words', type=int, default=11, help='Maximum words per sentence')
    parser.add_argument('--max-sentences', type=int, default=6, help='Maximum sentences per paragraph')
    parser.add_argument('--vocab', help='Path to vocabulary allowlist (one word per line)')
    parser.add_argument('--glossary', help='Path to glossary terms (one term per line)')
    parser.add_argument('--names', help='Path to proper names allowlist')
    parser.add_argument('--warn-only', action='store_true', help='Always exit 0')
    parser.add_argument('--require-glossary-section', action='store_true',
                       help='Require glossary terms to be defined')

    args = parser.parse_args()

    linter = Linter(
        max_words=args.max_words,
        max_sentences=args.max_sentences,
        vocab_file=args.vocab,
        glossary_file=args.glossary,
        names_file=args.names,
        warn_only=args.warn_only,
        require_glossary_section=args.require_glossary_section
    )

    if not linter.lint_file(args.file):
        sys.exit(1)

    linter.report()

    sys.exit(1 if linter.should_exit_error() else 0)


if __name__ == '__main__':
    main()
