# 그냥전당포.com

마인크래프트 도스온라인 서버의 전당포 사이트.
사장님이 자리에 없어도 감정신청(매입) / 구매신청을 받고, 관리자 페이지에서 처리한다.

- 유저 페이지 `/` : 판매 물품, 감정신청, 구매신청(선입금 + 입금내역 캡쳐), 내 신청 조회
- 관리자 페이지 `/admin` : 들어온 우편 물품, 감정가 입력, 신청 상태 관리, 재고, 공지
- Python 표준 라이브러리만 사용. 데이터는 `data/pawnshop.db` (SQLite), 신청 기록은 7일 후 자동 삭제.

## 로컬 실행

```
python server.py        # http://localhost:8080
python server.py 8123   # 다른 포트
```

첫 실행 후 `/admin`에서 관리자 비밀번호를 설정한다.

## 무료 호스팅 (GitHub 연동)

이 서버는 WSGI 앱(`server:application`)이라 대부분의 Python 호스팅에서 돌아간다.
GitHub Pages는 정적 페이지 전용이라 **불가** — 아래 방법을 쓴다.

### 방법 1. PythonAnywhere (추천 — 무료인데 데이터가 유지됨)

1. https://www.pythonanywhere.com 무료(Beginner) 가입
2. [Consoles] → Bash 열고:
   ```
   git clone https://github.com/<내아이디>/pawnshop.git
   ```
3. [Web] → Add a new web app → **Manual configuration** → Python 3.10
4. Code 섹션: Source code = `/home/<PA아이디>/pawnshop`
5. WSGI configuration file 클릭해서 내용을 전부 지우고:
   ```python
   import sys
   sys.path.insert(0, "/home/<PA아이디>/pawnshop")
   from server import application
   ```
6. [Reload] 버튼 → `https://<PA아이디>.pythonanywhere.com` 접속 끝.
7. 코드 수정 후 반영: Bash에서 `cd pawnshop && git pull` → Web 탭 [Reload]
   (무료 플랜은 3개월마다 [Run until 3 months from today] 버튼을 한 번 눌러줘야 유지됨)

### 방법 2. Render (GitHub 푸시하면 자동 배포 — 단, 데이터가 날아감)

1. https://render.com 가입 → New → Web Service → GitHub 저장소 연결
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `gunicorn server:application --bind 0.0.0.0:$PORT`

주의: 무료 플랜은 **재배포/재시작 때마다 `data/`가 초기화**된다 (비밀번호·재고·신청 전부).
15분 동안 접속이 없으면 잠들었다가 첫 방문자가 30초쯤 기다린다. 운영용으로는 비추천.

### 도메인 연결

가비아 등에서 `그냥전당포.com` (한글 도메인) 구매 후, 호스팅 주소로 CNAME/포워딩 연결.
PythonAnywhere 무료 플랜은 자체 도메인 연결이 안 되므로 도메인을 쓰려면 유료 플랜($5/월) 필요.

## 데이터

- `data/pawnshop.db` — 전체 데이터 (백업 = data 폴더 복사)
- `data/uploads/` — 입금내역 캡쳐 (관리자만 조회 가능)
- `data/`는 `.gitignore`로 깃허브에 올라가지 않음
- 보관 기간 변경: `server.py`의 `RETENTION_DAYS`
