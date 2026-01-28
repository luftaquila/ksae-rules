$pdflatex = "if [ -f formula_new.tex ]; then latexdiff --type=UNDERLINE formula.tex formula_new.tex > diff.tex; fi && pdflatex %O %S";
