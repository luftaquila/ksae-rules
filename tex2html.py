#!/usr/bin/env python3
"""
LaTeX to HTML converter with proper ref and cref resolution.
Parses .aux file to resolve references, then converts to HTML.
For pdflatex branch (formula_fixed.tex)
"""

import re
import sys
import subprocess
from pathlib import Path


def parse_nested_braces(s, start=0):
    """Parse content within nested braces starting at position start."""
    if start >= len(s) or s[start] != '{':
        return None, start

    depth = 0
    content_start = start + 1
    i = start

    while i < len(s):
        if s[i] == '{':
            depth += 1
        elif s[i] == '}':
            depth -= 1
            if depth == 0:
                return s[content_start:i], i + 1
        i += 1

    return None, start


def parse_aux_file(aux_path):
    """Parse .aux file to extract label references."""
    labels = {}

    with open(aux_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pos = 0
    while True:
        idx = content.find('\\newlabel{', pos)
        if idx == -1:
            break

        name_start = idx + len('\\newlabel{')
        name_end = content.find('}', name_start)
        if name_end == -1:
            pos = idx + 1
            continue

        label_name = content[name_start:name_end]

        if '@cref' in label_name:
            pos = name_end + 1
            continue

        first_brace = name_end + 1
        if first_brace < len(content) and content[first_brace] == '{':
            outer_content, next_pos = parse_nested_braces(content, first_brace)
            if outer_content:
                inner_content, _ = parse_nested_braces(outer_content, 0)
                if inner_content:
                    display = inner_content
                    display = display.replace('{}', '')
                    display = re.sub(r'\\relax\s*', '', display)
                    display = display.replace('~', ' ')
                    display = display.replace('{', '').replace('}', '')
                    labels[label_name] = display.strip()

        pos = name_end + 1

    return labels


def resolve_refs_in_tex(tex_content, labels):
    """Replace ref, cref, Cref with resolved values as links."""

    def get_label_display(label):
        if label in labels:
            return labels[label]
        return f'[{label}]'

    def make_link(label, text):
        anchor = label.replace(':', '-').replace(' ', '-')
        return f'\\hyperlink{{{anchor}}}{{{text}}}'

    def replace_cref(match):
        label = match.group(1)
        ref_text = get_label_display(label)

        if label.startswith('fig:'):
            display = f'그림 {ref_text}'
        elif label.startswith('section:'):
            display = f'제{ref_text}조'
        elif label.startswith('item:'):
            display = ref_text
        elif label.startswith('chapter:'):
            display = f'제{ref_text}장'
        else:
            display = ref_text

        return make_link(label, display)

    def replace_ref(match):
        label = match.group(1)
        return make_link(label, get_label_display(label))

    tex_content = re.sub(r'\\cref\{([^}]+)\}', replace_cref, tex_content)
    tex_content = re.sub(r'\\Cref\{([^}]+)\}', replace_cref, tex_content)
    tex_content = re.sub(r'\\ref\{([^}]+)\}', replace_ref, tex_content)
    tex_content = re.sub(r'\\pageref\{([^}]+)\}', '', tex_content)

    return tex_content


def preprocess_tex_for_pandoc(tex_content):
    """Preprocess LaTeX content for better pandoc compatibility."""

    chapter_counter = 0
    section_counter = 0
    figure_counter = 0

    # Remove input commands
    tex_content = re.sub(r'\\input\{template_fixed\}', '', tex_content)
    tex_content = re.sub(r'\\input\{template_fixed\.tex\}', '', tex_content)

    # Remove page style commands
    tex_content = re.sub(r'\\thispagestyle\{[^}]*\}', '', tex_content)
    tex_content = re.sub(r'\\pagestyle\{[^}]*\}', '', tex_content)

    # Remove CJK environment
    tex_content = re.sub(r'\\begin\{CJK\}\{[^}]*\}\{[^}]*\}', '', tex_content)
    tex_content = re.sub(r'\\end\{CJK\}', '', tex_content)

    # Remove color commands (for diff markup)
    # Handle {\color{blue}...} blocks that may span multiple lines
    def remove_color_blocks(tex):
        result = []
        i = 0
        while i < len(tex):
            # Check for {\color{
            if tex[i:i+8] == '{\\color{':
                # Find the closing } of color argument
                j = i + 8
                while j < len(tex) and tex[j] != '}':
                    j += 1
                j += 1  # Skip the }

                # Now we need to find the matching } for the outer {
                depth = 1
                content_start = j
                while j < len(tex) and depth > 0:
                    if tex[j] == '{':
                        depth += 1
                    elif tex[j] == '}':
                        depth -= 1
                    j += 1

                # Extract content without the outer braces and color command
                content = tex[content_start:j-1] if j > content_start else ''
                result.append(content)
                i = j
                continue

            result.append(tex[i])
            i += 1

        return ''.join(result)

    tex_content = remove_color_blocks(tex_content)
    # Handle \color{blue} without braces
    tex_content = re.sub(r'[\\]color\{[^}]*\}', '', tex_content)

    # Fix document header - combine title lines into one
    tex_content = re.sub(
        r'대학생 자작자동차대회\}\\\\.*?\n.*?Formula Student Korea 차량기술규정\}\\\\',
        r'대학생 자작자동차대회 Formula Student Korea 차량기술규정}\\\\',
        tex_content
    )

    # Convert \chapter{title}
    def replace_chapter(match):
        nonlocal chapter_counter
        chapter_counter += 1
        title = match.group(1)
        return f'\\chapter{{제{chapter_counter}장 {title}}}'

    tex_content = re.sub(r'\\chapter\{([^}]+)\}', replace_chapter, tex_content)

    # Convert \section{title}
    def replace_section(match):
        nonlocal section_counter
        section_counter += 1
        title = match.group(1)
        return f'\\section{{제{section_counter}조 ({title})}}'

    tex_content = re.sub(r'\\section\{([^}]+)\}', replace_section, tex_content)

    # Convert \fig{caption}{folder}{width}
    def replace_fig(match):
        nonlocal figure_counter
        figure_counter += 1
        caption = match.group(1)
        folder = match.group(2)
        width = match.group(3)
        anchor = f'fig-{caption}'.replace(' ', '-')

        return f'''\\begin{{figure}}[H]
\\hypertarget{{{anchor}}}{{}}
\\centering
\\includegraphics[width={width}\\linewidth]{{assets/{folder}/{caption}.jpg}}
\\caption{{그림 {figure_counter}. {caption}}}
\\end{{figure}}'''

    tex_content = re.sub(r'\\fig\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}', replace_fig, tex_content)

    # Remove fontsize commands
    tex_content = re.sub(r'\\fontsize\{[^}]*\}\{[^}]*\}\\selectfont\s*', '', tex_content)
    tex_content = re.sub(r'\\fontsize\{[^}]*\}\{[^}]*\}\s*', '', tex_content)

    # Handle \string[...] - remove \string
    tex_content = re.sub(r'\\string\[', '[', tex_content)
    tex_content = re.sub(r'\\string\]', ']', tex_content)

    # Convert \label to anchor
    def replace_label(match):
        label = match.group(1)
        anchor = label.replace(':', '-').replace(' ', '-')
        return f'\\hypertarget{{{anchor}}}{{}}'

    tex_content = re.sub(r'\\label\{([^}]+)\}', replace_label, tex_content)

    # Convert tblr environment to simple tabular
    def convert_tblr_env(tex):
        result = []
        i = 0
        while i < len(tex):
            # Find \begin{tblr}
            start = tex.find('\\begin{tblr}', i)
            if start == -1:
                result.append(tex[i:])
                break

            result.append(tex[i:start])

            # Find the matching \end{tblr}
            end_tag = '\\end{tblr}'
            end = tex.find(end_tag, start)
            if end == -1:
                result.append(tex[start:])
                break

            tblr_content = tex[start:end + len(end_tag)]

            # Extract content between options and \end{tblr}
            # Find where options end (after the first set of nested braces)
            brace_start = tblr_content.find('{', len('\\begin{tblr}'))
            if brace_start != -1:
                depth = 0
                options_end = brace_start
                for j in range(brace_start, len(tblr_content)):
                    if tblr_content[j] == '{':
                        depth += 1
                    elif tblr_content[j] == '}':
                        depth -= 1
                        if depth == 0:
                            options_end = j + 1
                            break

                table_content = tblr_content[options_end:tblr_content.rfind('\\end{tblr}')]
            else:
                table_content = ''

            # Clean up table content
            table_content = re.sub(r'\\SetCell\[[^\]]*\]\{[^}]*\}\s*', '', table_content)
            table_content = table_content.strip()

            # Count columns
            if table_content:
                first_row = table_content.split('\\\\')[0]
                num_cols = first_row.count('&') + 1
                colspec = '|' + 'c|' * num_cols

                # Convert to tabular
                converted = f'\\begin{{tabular}}{{{colspec}}}\n\\hline\n{table_content}\n\\hline\n\\end{{tabular}}'
                result.append(converted)
            else:
                result.append('')

            i = end + len(end_tag)

        return ''.join(result)

    tex_content = convert_tblr_env(tex_content)

    # Remove footnotesize and other size commands
    # Handle {\footnotesize ... } blocks by removing outer braces while preserving content
    def remove_footnotesize_block(tex):
        result = []
        i = 0

        while i < len(tex):
            # Check for {\footnotesize
            if tex[i:i+14] == '{\\footnotesize':
                # Find the end of this pattern
                j = i + 14
                while j < len(tex) and tex[j] in ' \t\n':
                    j += 1

                # Now find the matching } for the outer { by tracking depth
                depth = 1
                content_start = j
                while j < len(tex) and depth > 0:
                    if tex[j] == '{':
                        depth += 1
                    elif tex[j] == '}':
                        depth -= 1
                    j += 1

                # Extract content without outer braces and \footnotesize
                content = tex[content_start:j-1] if j > content_start else ''
                result.append(content)
                i = j
                continue

            result.append(tex[i])
            i += 1

        return ''.join(result)

    tex_content = remove_footnotesize_block(tex_content)
    tex_content = re.sub(r'\\footnotesize\s*', '', tex_content)

    # Remove any lone closing braces on their own line (cleanup)
    tex_content = re.sub(r'\n\s*\}\s*\n', '\n', tex_content)

    return tex_content


def add_heading_ids(html_content):
    """Add IDs to h1 and h2 tags for TOC navigation."""
    heading_counter = {'h1': 0, 'h2': 0}

    def add_id(match):
        tag = match.group(1)
        attrs = match.group(2) or ''
        content = match.group(3)

        # Skip if already has id
        if 'id="' in attrs:
            return match.group(0)

        heading_counter[tag] += 1
        # Create slug from content
        slug = re.sub(r'[^\w\s가-힣-]', '', content)
        slug = re.sub(r'\s+', '-', slug.strip())
        heading_id = f'{tag}-{heading_counter[tag]}-{slug[:30]}'

        if attrs:
            return f'<{tag} {attrs} id="{heading_id}">{content}</{tag}>'
        else:
            return f'<{tag} id="{heading_id}">{content}</{tag}>'

    html_content = re.sub(r'<(h1|h2)([^>]*)>([^<]+)</\1>', add_id, html_content)
    return html_content


def generate_toc(html_content):
    """Generate table of contents from h1 and h2 tags."""
    toc_items = []

    # Find all h1 (chapters) and h2 (sections) tags with id
    heading_pattern = re.compile(r'<(h1|h2)[^>]*id="([^"]*)"[^>]*>([^<]*)</\1>')

    for match in heading_pattern.finditer(html_content):
        level = match.group(1)
        heading_id = match.group(2)
        text = match.group(3).strip()

        if level == 'h1':
            toc_items.append(f'<a href="#{heading_id}" class="toc-chapter">{text}</a>')
        else:
            toc_items.append(f'<a href="#{heading_id}" class="toc-section">{text}</a>')

    return '\n      '.join(toc_items)


def postprocess_html(html_content):
    """Post-process the HTML output for better formatting."""

    def convert_hyperlink(match):
        target = match.group(1)
        text = match.group(2)
        return f'<a href="#{target}" class="ref-link">{text}</a>'

    html_content = re.sub(
        r'\\hyperlink\{([^}]+)\}\{([^}]+)\}',
        convert_hyperlink,
        html_content
    )

    def convert_hypertarget(match):
        target = match.group(1)
        return f'<span id="{target}"></span>'

    html_content = re.sub(
        r'\\hypertarget\{([^}]+)\}\{\}',
        convert_hypertarget,
        html_content
    )

    html_content = html_content.replace('\\%', '%')
    html_content = html_content.replace('\\&', '&amp;')
    html_content = html_content.replace('\\$', '$')

    # Add IDs to headings for TOC navigation
    html_content = add_heading_ids(html_content)

    # Generate and inject TOC
    toc_html = generate_toc(html_content)
    html_content = html_content.replace('<!-- TOC_PLACEHOLDER -->', toc_html)

    return html_content


def create_pandoc_template():
    """Create a custom pandoc HTML template."""
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>$title$</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&family=Noto+Serif+KR:wght@400;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="style.css">
  <script>
    MathJax = {
      tex: {
        inlineMath: [['$$', '$$'], ['\\\\(', '\\\\)']],
        displayMath: [['\\\\[', '\\\\]']]
      }
    };
  </script>
  <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
</head>
<body>
  <nav id="toc">
    <div class="toc-header">목차</div>
    <div class="toc-content">
      <!-- TOC_PLACEHOLDER -->
    </div>
  </nav>
  <button id="toc-toggle" aria-label="Toggle TOC">☰</button>
  <button id="theme-toggle" aria-label="Toggle Dark Mode">🌙</button>
  <button id="share-selection">🔗 링크 복사</button>
  <main id="content">
$body$
  </main>
  <script>
    // TOC Toggle
    const tocToggle = document.getElementById('toc-toggle');
    const toc = document.getElementById('toc');
    tocToggle.addEventListener('click', () => {
      toc.classList.toggle('open');
    });
    // Close TOC when clicking a link on mobile
    toc.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        if (window.innerWidth <= 1024) {
          toc.classList.remove('open');
        }
      });
    });

    // Dark Mode Toggle
    const themeToggle = document.getElementById('theme-toggle');
    const html = document.documentElement;

    // Check saved preference or system preference
    const savedTheme = localStorage.getItem('theme');
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    if (savedTheme === 'dark' || (!savedTheme && systemDark)) {
      html.setAttribute('data-theme', 'dark');
      themeToggle.textContent = '☀️';
    }

    themeToggle.addEventListener('click', () => {
      const isDark = html.getAttribute('data-theme') === 'dark';
      if (isDark) {
        html.removeAttribute('data-theme');
        localStorage.setItem('theme', 'light');
        themeToggle.textContent = '🌙';
      } else {
        html.setAttribute('data-theme', 'dark');
        localStorage.setItem('theme', 'dark');
        themeToggle.textContent = '☀️';
      }
    });

    // Text Selection Share Link
    const shareBtn = document.getElementById('share-selection');
    let selectedText = '';

    document.addEventListener('mouseup', (e) => {
      setTimeout(() => {
        const selection = window.getSelection();
        const text = selection.toString().trim();

        if (text.length > 3 && text.length < 200) {
          selectedText = text;
          const range = selection.getRangeAt(0);
          const rect = range.getBoundingClientRect();

          shareBtn.style.display = 'block';
          shareBtn.style.left = (rect.left + window.scrollX + rect.width / 2 - shareBtn.offsetWidth / 2) + 'px';
          shareBtn.style.top = (rect.top + window.scrollY - 40) + 'px';
          shareBtn.textContent = '🔗 링크 복사';
          shareBtn.classList.remove('copied');
        } else {
          shareBtn.style.display = 'none';
        }
      }, 10);
    });

    document.addEventListener('mousedown', (e) => {
      if (e.target !== shareBtn) {
        shareBtn.style.display = 'none';
      }
    });

    shareBtn.addEventListener('click', async () => {
      if (!selectedText) return;

      // Create URL with text fragment
      const baseUrl = window.location.href.split('#')[0];
      const encodedText = encodeURIComponent(selectedText);
      const url = baseUrl + '#:~:text=' + encodedText;

      try {
        await navigator.clipboard.writeText(url);
        shareBtn.textContent = '✓ 복사됨';
        shareBtn.classList.add('copied');
        setTimeout(() => {
          shareBtn.style.display = 'none';
        }, 1500);
      } catch (err) {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = url;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        shareBtn.textContent = '✓ 복사됨';
        shareBtn.classList.add('copied');
        setTimeout(() => {
          shareBtn.style.display = 'none';
        }, 1500);
      }
    });

    // Highlight text from URL fragment on page load
    (function() {
      const hash = window.location.hash;
      if (hash.includes(':~:text=')) {
        const textToFind = decodeURIComponent(hash.split(':~:text=')[1]);
        if (textToFind) {
          const walker = document.createTreeWalker(
            document.getElementById('content'),
            NodeFilter.SHOW_TEXT,
            null,
            false
          );

          let node;
          while (node = walker.nextNode()) {
            const idx = node.textContent.indexOf(textToFind);
            if (idx !== -1) {
              const range = document.createRange();
              range.setStart(node, idx);
              range.setEnd(node, idx + textToFind.length);

              const highlight = document.createElement('mark');
              highlight.className = 'text-highlight';
              range.surroundContents(highlight);

              highlight.scrollIntoView({ behavior: 'smooth', block: 'center' });
              break;
            }
          }
        }
      }
    })();
  </script>
</body>
</html>
'''


def convert_to_html(tex_path, output_path):
    """Main conversion function."""
    tex_path = Path(tex_path)
    output_path = Path(output_path)
    aux_path = tex_path.with_suffix('.aux')

    if not aux_path.exists():
        print(f"Error: {aux_path} not found. Please compile the LaTeX document first.")
        print("Run: pdflatex formula_fixed.tex (multiple times to resolve references)")
        sys.exit(1)

    print("Parsing .aux file for label references...")
    labels = parse_aux_file(aux_path)
    print(f"Found {len(labels)} labels")

    print("Reading LaTeX source...")
    with open(tex_path, 'r', encoding='utf-8') as f:
        tex_content = f.read()

    print("Resolving references...")
    tex_content = resolve_refs_in_tex(tex_content, labels)

    print("Preprocessing for pandoc...")
    tex_content = preprocess_tex_for_pandoc(tex_content)

    preprocessed_path = tex_path.with_name(tex_path.stem + '_preprocessed.tex')
    with open(preprocessed_path, 'w', encoding='utf-8') as f:
        f.write(tex_content)

    template_path = tex_path.with_name('pandoc_template.html')
    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(create_pandoc_template())

    print("Converting to HTML with pandoc...")
    cmd = [
        'pandoc',
        str(preprocessed_path),
        '-f', 'latex',
        '-t', 'html5',
        '-o', str(output_path),
        '--standalone',
        '--template', str(template_path),
        '--metadata', 'title=Formula Student Korea 차량기술규정',
        '--mathjax',
        '--wrap=none',
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Pandoc warnings/errors:\n{result.stderr}")
    except FileNotFoundError:
        print("Error: pandoc not found. Please install pandoc.")
        sys.exit(1)

    print("Post-processing HTML...")
    with open(output_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    html_content = postprocess_html(html_content)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # preprocessed_path.unlink(missing_ok=True)
    template_path.unlink(missing_ok=True)

    print(f"HTML output saved to: {output_path}")
    return output_path


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python tex2html.py <input.tex> [output.html]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else Path(input_file).with_suffix('.html')

    convert_to_html(input_file, output_file)
