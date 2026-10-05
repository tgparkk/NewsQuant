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
