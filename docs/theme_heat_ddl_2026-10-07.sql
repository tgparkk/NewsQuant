-- 네이버 테마 «열기»(마감 뒤 등락률) 수집용 DDL — 2026-10-07. 파일만 작성됨(미실행). 실행은 관리자가.
-- 기존 theme_snapshot_run / theme_daily / theme_member_daily 는 건드리지 않는다(08:00 소속 기록 불변).
-- 실행: psql -h 127.0.0.1 -p 5433 -U postgres -d kis_template -v ON_ERROR_STOP=1 -f docs/theme_heat_ddl_2026-10-07.sql
BEGIN;
CREATE TABLE theme_heat_run (
    run_id        bigserial   PRIMARY KEY,
    snap_date     date        NOT NULL,              -- KST 수집 시작 날짜
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text        NOT NULL CHECK (status IN ('running','ok','partial','failed','skipped')),
    n_themes      int,                               -- 상세를 받은 테마 수
    n_inserted    int,                               -- 이번 실행이 넣은 theme_heat_daily 행
    n_errors      int,
    market_status text,                              -- 목록 응답의 marketStatus (CLOSE 만 저장 대상)
    basis_date    date,                              -- 응답 기준일(종목 localTradedAt 최빈 날짜)
    note          text
);
CREATE INDEX idx_theme_heat_run_date ON theme_heat_run (snap_date, status);
CREATE TABLE theme_heat_daily (
    snap_date        date        NOT NULL,           -- 수집일(KST). 확정 응답만 저장하므로 basis_date 와 같다
    theme_no         int         NOT NULL,
    theme_name       text        NOT NULL,
    member_count     int,                            -- totalCount
    change_rate      numeric(8,2) NOT NULL,          -- 상세 groupInfo.changeRate = 구성종목 등락률의 동일가중 평균(검증됨)
    rise_count       int,
    fall_count       int,
    steady_count     int,
    list_change_rate numeric(8,2),                   -- 같은 시각 목록 응답 값(감사용 · 불일치 탐지)
    calc_change_rate numeric(8,2),                   -- 구성종목 fluctuationsRatio 평균 재계산(종목이 전부 왔을 때만)
    basis_date       date        NOT NULL,           -- 응답의 기준 거래일
    market_status    text        NOT NULL,           -- 항상 'CLOSE'
    fetched_at       timestamptz NOT NULL,
    run_id           bigint      NOT NULL REFERENCES theme_heat_run(run_id),
    PRIMARY KEY (snap_date, theme_no)
);
GRANT SELECT ON theme_heat_run, theme_heat_daily TO robotrader;
COMMIT;
