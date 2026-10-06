# NewsQuant — 네이버 테마 기록 수집기 설계 메모 (2026-10-05 · 승인 전 초안)

## 0. 사장님 결정 (문언 그대로)
- 「태쏘 아저씨 최근 글 보면 뉴스가 더욱 중요한거 같은데 "D:\GIT\NewsQuant" 개선점 없을까요?」
- 선택 = 「테마 기록 수집기부터 (Recommended)」 — 설계 메모 먼저 → 승인 → 구현 · 기존 수집기 불변 · 상한 ≈70만 · NewsQuant 브랜치 작업.

## 1. 목적
태쏘의 재료 = 「당일 뉴스 한 줄이 아니라 … 시장의 관심을 일정 기간 유지할 수 있는 재료」 + 테마 키워드.
우리 DB 에는 테마 축이 없다(KSIC 는 테마와 어긋남 — 2회 확인). 네이버 테마 소속·편입 사유·테마 설명을 **매일 그대로 찍어 두어**,
나중에 「그날 어떤 종목이 어떤 테마였고, 네이버가 뭐라고 설명했나」를 시점 그대로(PIT) 볼 수 있게 한다.
**과거 이력 API 가 없어 백필 불가 → 시작이 하루 늦을 때마다 그날 기록은 영구 손실.**

## 2. 수집 대상 (관리자 실측 2026-10-05 20:3x KST)
| 요청 | 주소 | 내용 |
|---|---|---|
| 목록 | `https://m.stock.naver.com/api/stocks/theme?page={1..3}&pageSize=100` | `groups[]`: no·name·totalCount·changeRate·riseCount·fallCount·steadyCount · `totalCount`=264 |
| 상세 | `https://m.stock.naver.com/api/stocks/theme/{no}?page={p}&pageSize=100` | `stocks[]`(itemCode·stockName·…) · `groupInfo` · **`themeDescription`**(테마 서사) · **`themeItemInfoMap`**{종목코드: 편입 사유} |

- 멤버 합 6,521 · 최대 148(테마 27) · 100 초과 3 테마 · `themeItemInfoMap` 은 페이지와 무관하게 전 멤버 수록(27: stocks 100 / map 148).
- 하루 요청 ≈ 3 + 264 + 3 = **≈270회** · 간격 1초 → 약 5분.
- 옛 `finance.naver.com/sise/theme.naver` 는 302 → 새 사이트(데이터는 위 API). **비공식 API** — 바뀌면 수집 실패(§6).

## 3. 저장 — 정확한 DDL (kis_template · 실행은 사장님 승인 뒤)
```sql
BEGIN;
CREATE TABLE theme_snapshot_run (
    run_id        bigserial   PRIMARY KEY,
    snap_date     date        NOT NULL,              -- KST 수집 시작 날짜
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text        NOT NULL CHECK (status IN ('running','ok','partial','failed')),
    n_themes      int,
    n_members     int,
    n_errors      int,
    market_status text,                              -- API 의 marketStatus (OPEN/CLOSE)
    note          text
);
CREATE TABLE theme_daily (
    snap_date     date        NOT NULL,
    theme_no      int         NOT NULL,
    theme_name    text        NOT NULL,
    description   text,                              -- themeDescription
    member_count  int,                               -- totalCount
    change_rate   numeric(8,2),                      -- 네이버 산출 테마 등락률
    rise_count    int,
    fall_count    int,
    steady_count  int,
    fetched_at    timestamptz NOT NULL,
    run_id        bigint      NOT NULL REFERENCES theme_snapshot_run(run_id),
    PRIMARY KEY (snap_date, theme_no)
);
CREATE TABLE theme_member_daily (
    snap_date     date        NOT NULL,
    theme_no      int         NOT NULL,
    stock_code    text        NOT NULL,
    stock_name    text,
    reason        text,                              -- themeItemInfoMap 값(편입 사유)
    fetched_at    timestamptz NOT NULL,
    run_id        bigint      NOT NULL REFERENCES theme_snapshot_run(run_id),
    PRIMARY KEY (snap_date, theme_no, stock_code)
);
CREATE INDEX idx_theme_member_daily_code ON theme_member_daily (stock_code, snap_date);
GRANT SELECT ON theme_snapshot_run, theme_daily, theme_member_daily TO robotrader;
COMMIT;
```
- 규모: 하루 ≈6,800행(테마 264 + 멤버 6,521) · 연 ≈170만 행 · 사유 텍스트 포함 연 ≈300MB 추정. **retention 정책 걸지 않음**(규칙).
- 가격·거래대금은 저장하지 않는다(SSOT = `daily_prices`). 테마 등락률·상승/하락 수만 «테마 열기» 지표로 남긴다.
- **PIT 규칙**: INSERT `ON CONFLICT DO NOTHING` — 하루의 첫 관측만 남는다. 같은 날 재실행은 빠진 테마만 채운다(덮어쓰기 0).
- 원본 JSON 은 하루치를 gzip 으로 `D:/archive/naver-theme-snapshots/YYYY/YYYY-MM-DD.json.gz` 에 보관(재파싱 대비 · 하루 ≈1MB 추정).

## 4. 실행 방식
- 새 파일만: `news_scraper/theme_snapshot.py`(가져오기·파싱·저장) · `scripts/snapshot_naver_themes.py`(CLI · `--dry-run`) · `tests/test_theme_snapshot.py` + `tests/fixtures/` 응답 2개 · `docs/theme_snapshot_2026-10-05.md`(이 메모) · DDL 파일.
- **기존 스케줄러·크롤러·`news` 표·섹터 계열 변경 0 · 재기동 0**(09-16 패널 D5 준수). DB 설정은 기존 `config.yaml` 을 읽기만.
- 예의: 요청 간 1초 이상 · 실패 재시도 3회(기존 `http_guard` 의 `AdaptiveDelay`·`CircuitBreaker` 재사용) · 연속 실패 시 중단하고 run=`failed`.
- 주기: **Windows 작업 스케줄러 새 작업 `kis-newsquant-theme-snapshot` · 매일 18:10**(주말·휴장 포함 — 네이버 편집은 휴일에도 있음) · `StartWhenAvailable=True`(PC 꺼져 있던 날은 켜지면 따라잡기).
- 소비자 연결 0: 봇·LLM shadow·태쏘 러너 어디에도 연결하지 않는다(쌓기만). 활용(지속력 표·테마 열기)은 10-16 뒤 별도 결정.

## 5. 검증
1. 단위 테스트: 저장한 실제 응답(작은 테마 586 · 목록 1페이지)으로 파서 → 행 수·필드·종목코드 6자리.
2. `--dry-run` 1회(DB 쓰기 0): 테마 264±, 멤버 6,521± 인쇄.
3. 실제 1회 → 행 수 · 중복 0 · `stock_info` 와 종목코드 교집합 비율 인쇄 · 같은 날 재실행 → 새 행 0(멱등).
4. verifier(sonnet) 1패스 — 기존 테스트 전체 통과 + 위 1~3 증거.

## 6. 위험
- 비공식 API 변경·차단 → run 행 `failed` + 로그 · 관리자가 주 1회 run 표 확인(경보 연결은 후속).
- 이용 약관: 내부 연구용 저장만 · 재배포 없음.
- 이 세션은 원래 「DB SELECT 만」 — DDL·INSERT 는 **사장님 명시 승인 사항**.

## 7. 절차·비용
- NewsQuant 라이브 폴더(`D:/GIT/NewsQuant`)는 수집기가 돌고 있어 브랜치 전환 금지 → 워크트리 `D:/tmp/nq-wt-theme-snapshot` · 브랜치 `feat/theme-snapshot`(base `542884f`).
- executor sonnet 1(≤35만) + verifier sonnet 1(≤20만) + 관리자 ≈10만 = **≈65만**(상한 70만 안).
- 순서: 승인 → 구현·테스트 → DDL 실행(오늘 휴장·20시 이후라 오늘 밤 가능) → 첫 수집 = 오늘 밤 수동 1회(10-05 기록 확보) → 작업 스케줄러 등록 → 커밋은 브랜치 · push·main 머지는 사장님 확인.

## 8. 운영 기록
- **2026-10-05** 실행 시각을 18:10 → **매일 08:00**으로 바꿔 등록(장 전에 알 수 있던 소속을 남기려는 목적 · PC 가 저녁에 꺼지는 날이 있음). 첫 수동 run 10-05 20:57 ok.
- **2026-10-06 08:00 run 에서 지표 0 발견.** 장 전(PREOPEN)에는 상세 API `groupInfo` 의 totalCount·changeRate·rise/fall/steadyCount 가 모두 0 으로 비어 온다.
  같은 시각 목록 API 도 일부 테마만 0 으로 비어(등락률 0 = 64테마 · totalCount 합 5,163) 대체값으로 쓸 수 없다. 상세 최상위 `totalCount` 는 정상.
  - 수정: `groupInfo.totalCount == 0` 인데 테마에 종목이 있으면 «장 전 초기화»로 보고 `member_count` = 상세 최상위 totalCount, 등락률·상승/하락/보합 수 = **NULL**. run note 에 «장 전 초기화 N테마» 기록.
  - 10-06 행 264개는 원본 gz 를 고친 파서로 다시 읽어 1회 보정(UPDATE · PIT «덮어쓰기 0»의 예외 · 사장님 승인). run 2 note 에 보정 사실 기록.
  - 결과: 08:00 실행에서는 `theme_daily` 의 등락률·상승/하락/보합 칸이 매일 NULL 이다. 테마 열기는 소속(`theme_member_daily`) + `daily_prices` 로 계산한다(SSOT 원칙과 같음).
- 장 전에는 큰 테마(예: 27)의 상세 2쪽 `stocks[]` 가 덜 내려와 종목명이 빈 행이 생길 수 있다(10-06: 5행). 사유와 소속은 `themeItemInfoMap` 기준이라 빠지지 않는다.
