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
    tex_content = re.sub(r'\\color\{[^}]*\}', '', tex_content)
    tex_content = re.sub(r'\{\\color\{[^}]*\}([^}]*)\}', r'\1', tex_content)

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

    return tex_content


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
$body$
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

    preprocessed_path.unlink(missing_ok=True)
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
