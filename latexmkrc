$pdf_mode = 4;  # lualatex
$lualatex = "if [ -f formula_new.tex ]; then latexdiff --type=UNDERLINE formula.tex formula_new.tex > diff.tex; fi && lualatex %O %S";
