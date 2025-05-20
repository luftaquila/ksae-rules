#! /bin/bash
set -e

sudo ./bin/docker-compose exec -it sharelatex tlmgr update --self
sudo ./bin/docker-compose exec -it sharelatex tlmgr install pgf float collection-langkorean luatexko caption enumitem multirow titlesec tabularray ninecolors cleveref newfloat

sudo ./bin/docker-compose exec -it sharelatex mkdir -p temp

sudo ./bin/docker-compose exec -it sharelatex wget https://github.com/orioncactus/pretendard/releases/download/v1.3.9/Pretendard-1.3.9.zip -O temp/pretendard.zip
sudo ./bin/docker-compose exec -it sharelatex unzip temp/pretendard.zip -d temp
sudo ./bin/docker-compose exec -it sharelatex mv temp/public/static/alternative fonts
sudo ./bin/docker-compose exec -it sharelatex rm -rf temp

sudo ./bin/docker-compose exec -it sharelatex wget https://hangeul.naver.com/hangeul_static/webfont/zips/nanum-myeongjo.zip -O fonts/nanum-myeongjo.zip
sudo ./bin/docker-compose exec -it sharelatex unzip fonts/nanum-myeongjo.zip -d fonts
sudo ./bin/docker-compose exec -it sharelatex rm fonts/nanum-myeongjo.zip

sudo ./bin/docker-compose exec -it sharelatex wget https://github.com/notofonts/noto-cjk/raw/refs/heads/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf -O fonts/NotoSansCJKtc-Regular.otf

sudo ./bin/docker-compose exec -it sharelatex cp -r fonts /usr/local/share/fonts/overleaf
sudo ./bin/docker-compose exec -it sharelatex fc-cache -fv
