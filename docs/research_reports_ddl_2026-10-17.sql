-- 증권사 리서치 리포트(네이버 증권 종목분석) — kis_template · 실행은 사장님 승인 뒤
-- 수집: news_scraper/research_collector.py(30분 정방향) · scripts/backfill_research_reports.py(2년 백필)
-- UPSERT(nid) 는 read_count·updated_at 만 갱신한다. first_seen_at·backfilled·본문 필드는 처음 본 그대로(시점 무결성).
-- 시점 기준 분석은 backfilled=FALSE 행의 first_seen_at 을 쓴다(백필 행의 first_seen_at 은 백필 시각).
BEGIN;
CREATE TABLE research_reports (
    nid            bigint      PRIMARY KEY,           -- 네이버 리포트 번호
    write_date     date        NOT NULL,              -- writeDate(작성일)
    item_code      varchar(12),                       -- 종목코드
    item_name      text,
    broker_code    varchar(16),
    broker_name    text,
    title          text        NOT NULL,
    summary        text,                              -- content HTML → 일반 텍스트(줄바꿈 유지)
    goal_price     bigint,                            -- 목표주가 · 빈값/0/해석불가 → NULL
    opinion_text   text,                              -- 예: Buy
    opinion_type   text,                              -- 예: buy
    read_count     integer,                           -- 조회수(UPSERT 때 갱신)
    backfilled     boolean     NOT NULL DEFAULT FALSE,
    first_seen_at  timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_research_reports_item_date ON research_reports (item_code, write_date);
CREATE INDEX idx_research_reports_write_date ON research_reports (write_date);
GRANT SELECT ON research_reports TO robotrader;
COMMIT;
