#!/usr/bin/env python3
"""
KSAE Formula Rules VectorDB Indexer
Parses formula.tex, chunks by section/item hierarchy, and indexes into Qdrant.
"""

import argparse
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


# Configuration
QDRANT_URL = "https://vectordb.luftaquila.io"
COLLECTION_NAME = "ksae-formula-rules"
EMBEDDING_MODEL = "BAAI/bge-m3"
EMBEDDING_DIM = 1024

# Chunking
MAX_CHUNK_TOKENS = 512  # target max tokens per chunk (approx)
# Korean chars ≈ 1~2 tokens each; conservative estimate: 1 char ≈ 1.5 tokens
CHARS_PER_TOKEN = 1.5


def get_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ── LaTeX cleanup ──────────────────────────────────────────────────────────

def strip_latex(text: str) -> str:
    """Strip LaTeX markup, converting to readable plain text."""
    s = text

    # Remove \color{...} commands (keep content)
    # Handle {\color{blue} text} → text (paired braces)
    s = re.sub(r'\{\\color\{[^}]*\}\s*([^}]*)\}', r'\1', s)
    # Handle standalone \color{blue} without outer braces
    s = re.sub(r'\\color\{[^}]*\}', '', s)

    # Remove figure references - convert to descriptive text
    s = re.sub(r'\\figref\{fig:([^}]*)\}', r'(\1 그림 참고)', s)
    s = re.sub(r'\\fig\{([^}]*)\}\{[^}]*\}\{[^}]*\}', r'[그림: \1]', s)

    # Convert \ref{...} to descriptive text
    s = re.sub(r'\\ref\{(?:section|chapter|item):([^}]*)\}', r'[\1]', s)
    s = re.sub(r'\\ref\{([^}]*)\}', r'[\1]', s)

    # Remove \label{...}
    s = re.sub(r'\\label\{[^}]*\}', '', s)

    # Handle \string[...] → [...]
    s = re.sub(r'\\string\[', '[', s)
    s = re.sub(r'\\string\]', ']', s)
    s = re.sub(r'\\string~', '~', s)

    # Remove entire table/tblr/figure environments (they don't embed well)
    s = re.sub(r'\\begin\{table\}.*?\\end\{table\}', '', s, flags=re.DOTALL)
    s = re.sub(r'\\begin\{figure\}.*?\\end\{figure\}', '', s, flags=re.DOTALL)
    s = re.sub(r'\\begin\{tblr\}.*?\\end\{tblr\}', '', s, flags=re.DOTALL)

    # Remove common LaTeX commands
    s = re.sub(r'\\(?:begin|end)\{(?:enumerate|itemize|description|center)\}(?:\[.*?\])?', '', s)
    s = re.sub(r'\\item\b', '•', s)

    # Remove \begin{...}/\end{...} for any remaining environments
    s = re.sub(r'\\(?:begin|end)\{[^}]*\}(?:\{[^}]*\})*(?:\[[^\]]*\])?', '', s)

    # Remove formatting commands
    s = re.sub(r'\\(?:textbf|textit|texttt|emph|underline)\{([^}]*)\}', r'\1', s)
    s = re.sub(r'\\(?:pretendardb|footnotesize|bfseries|centering)\b', '', s)
    s = re.sub(r'\\(?:fontsize|selectfont|addfontfeatures|SetCell|hline|vline)\b[^\\]*', '', s)

    # Remove spacing/layout commands
    s = re.sub(r'\\(?:vspace|hspace|vfill|hfill|noindent|hrule)\b(?:\{[^}]*\})?', '', s)
    s = re.sub(r'\\\\\s*(?:\[.*?\])?', '\n', s)  # \\ linebreak → newline
    s = re.sub(r'\\\\', '\n', s)

    # Remove misc commands
    s = re.sub(r'\\(?:qquad|quad)\b', ' ', s)
    s = re.sub(r'\\%', '%', s)
    s = re.sub(r'\\&', '&', s)
    s = re.sub(r'\\mathrm\{([^}]*)\}', r'\1', s)

    # Remove any remaining LaTeX commands
    s = re.sub(r'\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})*', '', s)

    # Remove orphaned braces
    s = re.sub(r'\{([^}]*)\}', r'\1', s)

    # Keep math expressions readable
    s = re.sub(r'\$([^$]+)\$', r'\1', s)

    # Clean up whitespace
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    s = re.sub(r'^\s+$', '', s, flags=re.MULTILINE)

    return s.strip()


# ── LaTeX parser ───────────────────────────────────────────────────────────

@dataclass
class Section:
    chapter: str
    chapter_num: int
    section_title: str
    section_num: int
    raw_content: str
    start_line: int
    end_line: int
    applies_to: list[str] = field(default_factory=list)


def detect_applies_to(title: str, content: str) -> list[str]:
    """Detect if section applies to C-Formula, E-Formula, or both."""
    combined = title + " " + content

    # Only restrict to one type if the chapter/section title explicitly says "해당"
    if re.search(r'C-Formula\s*해당', combined) and not re.search(r'E-Formula\s*해당', combined):
        return ["C-Formula"]
    if re.search(r'E-Formula\s*해당', combined) and not re.search(r'C-Formula\s*해당', combined):
        return ["E-Formula"]

    # Also check for standalone markers like [C-Formula만 해당] or [E-Formula만 해당]
    if re.search(r'\[?\s*C-Formula만\s*해당\s*\]?', combined) and not re.search(r'E-Formula', combined):
        return ["C-Formula"]
    if re.search(r'\[?\s*E-Formula만\s*해당\s*\]?', combined) and not re.search(r'C-Formula', combined):
        return ["E-Formula"]

    # Default: applies to both (even if one type is mentioned incidentally)
    return ["C-Formula", "E-Formula"]


def parse_sections(tex_path: str) -> list[Section]:
    """Parse LaTeX file into sections."""
    with open(tex_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    sections = []
    current_chapter = ""
    current_chapter_num = 0
    current_section = ""
    current_section_num = 0
    current_lines = []
    current_start = 0

    def extract_brace_content(line: str, cmd: str) -> str | None:
        """Extract content from \\cmd{...} handling nested braces."""
        idx = line.find(f'\\{cmd}{{')
        if idx < 0:
            return None
        start = idx + len(cmd) + 2  # skip \cmd{
        depth = 1
        i = start
        while i < len(line) and depth > 0:
            if line[i] == '{':
                depth += 1
            elif line[i] == '}':
                depth -= 1
            i += 1
        return line[start:i - 1] if depth == 0 else None

    def flush_section():
        if current_section and current_lines:
            raw = "".join(current_lines)
            sections.append(Section(
                chapter=current_chapter,
                chapter_num=current_chapter_num,
                section_title=current_section,
                section_num=current_section_num,
                raw_content=raw,
                start_line=current_start,
                end_line=current_start + len(current_lines) - 1,
                applies_to=detect_applies_to(
                    current_chapter + " " + current_section, raw
                ),
            ))

    for i, line in enumerate(lines):
        ch_title = extract_brace_content(line, 'chapter')
        sec_title = extract_brace_content(line, 'section')

        if ch_title is not None:
            flush_section()
            current_chapter_num += 1
            current_chapter = strip_latex(ch_title).strip()
            current_section = ""
            current_section_num = 0
            current_lines = []
            current_start = i + 1
            continue

        if sec_title is not None:
            flush_section()
            current_section_num += 1
            current_section = strip_latex(sec_title).strip()
            current_lines = []
            current_start = i + 1
            continue

        if current_section:
            current_lines.append(line)

    flush_section()
    return sections


# ── Chunking ───────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    text: str
    chapter: str
    chapter_num: int
    section: str
    section_num: int
    item_range: str
    applies_to: list[str]
    source_lines: str


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN)


def split_section_by_items(content: str) -> list[tuple[str, str]]:
    """
    Split section content by top-level \\item boundaries.
    Returns list of (item_label, item_content) tuples.
    """
    # Find top-level \item positions by tracking enumerate depth
    lines = content.split('\n')
    items = []
    current_item_lines = []
    current_item_num = 0
    preamble_lines = []  # lines before first \item
    depth = 0
    in_first_enum = False

    for line in lines:
        # Track enumerate depth
        if re.search(r'\\begin\{enumerate\}', line):
            if not in_first_enum:
                in_first_enum = True
                depth = 1
            else:
                depth += 1
        if re.search(r'\\end\{enumerate\}', line):
            depth -= 1
            if depth < 0:
                depth = 0

        # Check if this is a top-level \item
        is_top_item = (depth == 1 and re.match(r'\s*\\item\b', line))

        if is_top_item:
            if current_item_lines:
                items.append((str(current_item_num), '\n'.join(current_item_lines)))
            current_item_num += 1
            current_item_lines = [line]
        elif in_first_enum:
            current_item_lines.append(line)
        else:
            preamble_lines.append(line)

    if current_item_lines:
        items.append((str(current_item_num), '\n'.join(current_item_lines)))

    # If there's preamble, prepend it to first item or make it its own chunk
    preamble = '\n'.join(preamble_lines).strip()
    if preamble and items:
        first_label, first_content = items[0]
        items[0] = (first_label, preamble + '\n' + first_content)
    elif preamble:
        items = [("0", preamble)]

    return items


def chunk_section(section: Section) -> list[Chunk]:
    """Chunk a section into appropriately sized pieces."""
    clean_content = strip_latex(section.raw_content)
    prefix = f"[Formula Student Korea 차량기술규정] 제{section.chapter_num}장 {section.chapter} > {section.section_title}\n\n"

    total_tokens = estimate_tokens(prefix + clean_content)

    # If section fits in one chunk, return as-is
    if total_tokens <= MAX_CHUNK_TOKENS:
        return [Chunk(
            text=prefix + clean_content,
            chapter=section.chapter,
            chapter_num=section.chapter_num,
            section=section.section_title,
            section_num=section.section_num,
            item_range="all",
            applies_to=section.applies_to,
            source_lines=f"{section.start_line}-{section.end_line}",
        )]

    # Split by top-level items
    items = split_section_by_items(section.raw_content)

    if not items:
        return [Chunk(
            text=prefix + clean_content,
            chapter=section.chapter,
            chapter_num=section.chapter_num,
            section=section.section_title,
            section_num=section.section_num,
            item_range="all",
            applies_to=section.applies_to,
            source_lines=f"{section.start_line}-{section.end_line}",
        )]

    # Group items into chunks that fit within token limit
    chunks = []
    current_items = []
    current_text = ""
    current_item_start = ""
    current_item_end = ""

    for item_label, item_raw in items:
        item_clean = strip_latex(item_raw)
        candidate = current_text + ("\n\n" if current_text else "") + item_clean

        if estimate_tokens(prefix + candidate) > MAX_CHUNK_TOKENS and current_items:
            # Flush current group
            chunks.append(Chunk(
                text=prefix + current_text,
                chapter=section.chapter,
                chapter_num=section.chapter_num,
                section=section.section_title,
                section_num=section.section_num,
                item_range=f"{current_item_start}-{current_item_end}",
                applies_to=section.applies_to,
                source_lines=f"{section.start_line}-{section.end_line}",
            ))
            current_items = []
            current_text = ""
            current_item_start = ""

        if not current_items:
            current_item_start = item_label

        current_items.append(item_label)
        current_item_end = item_label
        current_text = candidate if current_text else item_clean

    # Flush remaining
    if current_items:
        chunks.append(Chunk(
            text=prefix + current_text,
            chapter=section.chapter,
            chapter_num=section.chapter_num,
            section=section.section_title,
            section_num=section.section_num,
            item_range=f"{current_item_start}-{current_item_end}",
            applies_to=section.applies_to,
            source_lines=f"{section.start_line}-{section.end_line}",
        ))

    # Handle oversized single items - split by paragraphs
    final_chunks = []
    for chunk in chunks:
        if estimate_tokens(chunk.text) > MAX_CHUNK_TOKENS * 1.5:
            sub_chunks = split_oversized_chunk(chunk, prefix)
            final_chunks.extend(sub_chunks)
        else:
            final_chunks.append(chunk)

    return final_chunks


def split_oversized_chunk(chunk: Chunk, prefix: str) -> list[Chunk]:
    """Split an oversized chunk by paragraphs."""
    # Remove prefix to work with content only
    content = chunk.text[len(prefix):] if chunk.text.startswith(prefix) else chunk.text
    paragraphs = re.split(r'\n\n+', content)

    sub_chunks = []
    current_text = ""
    part = 1

    for para in paragraphs:
        candidate = current_text + ("\n\n" if current_text else "") + para

        if estimate_tokens(prefix + candidate) > MAX_CHUNK_TOKENS and current_text:
            sub_chunks.append(Chunk(
                text=prefix + current_text,
                chapter=chunk.chapter,
                chapter_num=chunk.chapter_num,
                section=chunk.section,
                section_num=chunk.section_num,
                item_range=f"{chunk.item_range} (part {part})",
                applies_to=chunk.applies_to,
                source_lines=chunk.source_lines,
            ))
            current_text = para
            part += 1
        else:
            current_text = candidate

    if current_text:
        sub_chunks.append(Chunk(
            text=prefix + current_text,
            chapter=chunk.chapter,
            chapter_num=chunk.chapter_num,
            section=chunk.section,
            section_num=chunk.section_num,
            item_range=f"{chunk.item_range} (part {part})" if part > 1 else chunk.item_range,
            applies_to=chunk.applies_to,
            source_lines=chunk.source_lines,
        ))

    return sub_chunks if sub_chunks else [chunk]


# ── Indexing ───────────────────────────────────────────────────────────────

def generate_point_id(chapter: int, section: int, chunk_index: int) -> int:
    hash_input = f"ksae-formula:{chapter}:{section}:{chunk_index}"
    hash_bytes = hashlib.md5(hash_input.encode()).digest()
    return int.from_bytes(hash_bytes[:8], byteorder="big") & 0x7FFFFFFFFFFFFFFF


def index_chunks(client, model, chunks: list[Chunk], recreate: bool = False, batch_size: int = 8) -> None:
    """Embed chunks and upload to Qdrant."""
    from qdrant_client.models import Distance, VectorParams, PointStruct
    from tqdm import tqdm

    collections = [c.name for c in client.get_collections().collections]

    if COLLECTION_NAME in collections:
        if recreate:
            print(f"Deleting existing collection: {COLLECTION_NAME}")
            client.delete_collection(COLLECTION_NAME)
        else:
            info = client.get_collection(COLLECTION_NAME)
            print(f"Collection already exists: {COLLECTION_NAME} ({info.points_count} points)")
            print("Use --recreate to rebuild")
            return

    print(f"Creating collection: {COLLECTION_NAME}")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
    )

    # Generate embeddings
    print(f"\nGenerating embeddings for {len(chunks)} chunks...")
    texts = [c.text for c in chunks]
    embeddings = []

    for i in tqdm(range(0, len(texts), batch_size), desc="Embedding"):
        batch = texts[i:i + batch_size]
        batch_emb = model.encode(batch, show_progress_bar=False)
        embeddings.extend(batch_emb)

    # Build points
    print("\nUploading to Qdrant...")
    points = []

    for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point_id = generate_point_id(chunk.chapter_num, chunk.section_num, idx)
        points.append(PointStruct(  # noqa: imported above
            id=point_id,
            vector=embedding.tolist(),
            payload={
                "content": chunk.text,
                "chapter": chunk.chapter,
                "chapter_num": chunk.chapter_num,
                "section": chunk.section,
                "section_num": chunk.section_num,
                "item_range": chunk.item_range,
                "applies_to": chunk.applies_to,
                "source_lines": chunk.source_lines,
            },
        ))

    # Upload in batches
    upload_batch = 100
    for i in tqdm(range(0, len(points), upload_batch), desc="Uploading"):
        batch = points[i:i + upload_batch]
        client.upsert(collection_name=COLLECTION_NAME, points=batch)

    info = client.get_collection(COLLECTION_NAME)
    print(f"\nDone! Collection '{COLLECTION_NAME}': {info.points_count} points")


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Index KSAE Formula rules into Qdrant vector database"
    )
    parser.add_argument(
        "--tex",
        default=str(Path(__file__).parent / "formula.tex"),
        help="Path to formula.tex (default: ./formula.tex)",
    )
    parser.add_argument(
        "--url",
        default=QDRANT_URL,
        help=f"Qdrant server URL (default: {QDRANT_URL})",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Qdrant API key",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate collection if it exists",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "mps", "cuda"],
        default="auto",
        help="Device for embedding computation (default: auto)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Batch size for embedding (default: 8)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and chunk only, print results without uploading",
    )
    parser.add_argument(
        "--search",
        type=str,
        help="Search query (instead of indexing)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of search results (default: 5)",
    )

    args = parser.parse_args()

    # ── Search mode ──────────────────────────────────────────────────
    if args.search:
        from qdrant_client import QdrantClient
        from sentence_transformers import SentenceTransformer

        device = args.device if args.device != "auto" else get_device()
        print(f"Using device: {device}")
        print(f"Loading model: {EMBEDDING_MODEL}...")
        model = SentenceTransformer(EMBEDDING_MODEL, device=device)

        client = QdrantClient(
            host=args.url.replace("https://", "").replace("http://", "").rstrip("/"),
            port=443,
            https=args.url.startswith("https"),
            api_key=args.api_key,
            prefer_grpc=False,
            timeout=60,
        )
        query_vector = model.encode(args.search).tolist()

        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=args.limit,
        )

        print(f"\nSearch: \"{args.search}\"\n")
        for i, hit in enumerate(results.points, 1):
            p = hit.payload
            print(f"── Result {i} (score: {hit.score:.4f}) ──")
            print(f"  Chapter {p['chapter_num']}: {p['chapter']}")
            print(f"  Section: {p['section']}")
            print(f"  Items: {p['item_range']} | Applies to: {', '.join(p['applies_to'])}")
            print(f"  Lines: {p['source_lines']}")
            print(f"  Content:\n{p['content'][:400]}...")
            print()
        return 0

    # ── Parse & chunk ────────────────────────────────────────────────
    print(f"Parsing {args.tex}...")
    sections = parse_sections(args.tex)
    print(f"Found {len(sections)} sections")

    all_chunks = []
    for section in sections:
        chunks = chunk_section(section)
        all_chunks.extend(chunks)

    print(f"Created {len(all_chunks)} chunks")

    # Stats
    token_counts = [estimate_tokens(c.text) for c in all_chunks]
    print(f"Token range: {min(token_counts)}~{max(token_counts)}, avg: {sum(token_counts) / len(token_counts):.0f}")

    if args.dry_run:
        print("\n── Dry run: chunk details ──\n")
        for i, chunk in enumerate(all_chunks):
            print(f"[{i:3d}] Ch{chunk.chapter_num} {chunk.chapter} > {chunk.section}")
            print(f"      items={chunk.item_range}, applies_to={chunk.applies_to}, ~{estimate_tokens(chunk.text)} tokens")
            print(f"      {chunk.text[:120]}...")
            print()
        return 0

    # ── Index ────────────────────────────────────────────────────────
    from qdrant_client import QdrantClient
    from sentence_transformers import SentenceTransformer

    device = args.device if args.device != "auto" else get_device()
    print(f"\nUsing device: {device}")
    print(f"Loading model: {EMBEDDING_MODEL}...")
    model = SentenceTransformer(EMBEDDING_MODEL, device=device)

    print(f"Connecting to Qdrant at {args.url}...")
    client = QdrantClient(
            host=args.url.replace("https://", "").replace("http://", "").rstrip("/"),
            port=443,
            https=args.url.startswith("https"),
            api_key=args.api_key,
            prefer_grpc=False,
            timeout=60,
        )

    index_chunks(client, model, all_chunks, args.recreate, args.batch_size)

    return 0


if __name__ == "__main__":
    exit(main())
