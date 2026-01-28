# Formula Student Korea 차량기술규정 빌드 스크립트 (lualatex)

TEX = formula.tex
PDF = formula.pdf
HTML = formula.html
AUX = formula.aux
SCRIPT = tex2html.py
CSS = style.css

# 기본 타겟
all: pdf html

# PDF 생성 (3번 컴파일하여 참조 해결)
pdf: $(PDF)

$(PDF): $(TEX) template.tex
	@echo "==> LuaLaTeX 1차 컴파일..."
	lualatex -interaction=nonstopmode $(TEX) > /dev/null 2>&1 || true
	@echo "==> LuaLaTeX 2차 컴파일..."
	lualatex -interaction=nonstopmode $(TEX) > /dev/null 2>&1 || true
	@echo "==> LuaLaTeX 3차 컴파일..."
	lualatex -interaction=nonstopmode $(TEX) > /dev/null 2>&1 || true
	@echo "==> PDF 생성 완료: $(PDF)"

# HTML 생성 (PDF가 먼저 생성되어야 .aux 파일 존재)
html: $(HTML)

$(HTML): $(TEX) $(AUX) $(SCRIPT) $(CSS)
	@echo "==> HTML 변환 중..."
	python3 $(SCRIPT) $(TEX) $(HTML)
	@echo "==> HTML 생성 완료: $(HTML)"

# .aux 파일 생성 (PDF 빌드 시 자동 생성)
$(AUX): $(PDF)

# HTML만 빌드 (PDF가 이미 있다고 가정)
html-only:
	@if [ ! -f $(AUX) ]; then \
		echo "Error: $(AUX) 파일이 없습니다. 먼저 'make pdf'를 실행하세요."; \
		exit 1; \
	fi
	python3 $(SCRIPT) $(TEX) $(HTML)
	@echo "==> HTML 생성 완료: $(HTML)"

# 빌드 결과물 삭제
clean:
	@echo "==> 임시 파일 삭제..."
	rm -f *.aux *.log *.out *.toc *.lof *.lot *.bbl *.blg *.bcf
	rm -f *.run.xml *.synctex.gz *.fls *.fdb_latexmk
	rm -f *.4tc *.4ct *.tmp *.xref *.idv *.lg *.dvi
	rm -f *_preprocessed.tex pandoc_template.html
	@echo "==> 삭제 완료"

# 모든 생성 파일 삭제
distclean: clean
	@echo "==> 결과물 삭제..."
	rm -f $(PDF) $(HTML)
	@echo "==> 삭제 완료"

# 브라우저에서 HTML 열기
view: $(HTML)
	@echo "==> 브라우저에서 열기..."
	open $(HTML)

# PDF 뷰어에서 열기
view-pdf: $(PDF)
	@echo "==> PDF 뷰어에서 열기..."
	open $(PDF)

# 도움말
help:
	@echo "사용 가능한 타겟:"
	@echo "  make          - PDF와 HTML 모두 생성"
	@echo "  make pdf      - PDF만 생성"
	@echo "  make html     - HTML 생성 (PDF 먼저 빌드)"
	@echo "  make html-only- HTML만 생성 (PDF가 이미 있을 때)"
	@echo "  make clean    - 임시 파일 삭제"
	@echo "  make distclean- 모든 생성 파일 삭제"
	@echo "  make view     - 브라우저에서 HTML 열기"
	@echo "  make view-pdf - PDF 뷰어에서 열기"
	@echo "  make help     - 이 도움말 표시"

.PHONY: all pdf html html-only clean distclean view view-pdf help
