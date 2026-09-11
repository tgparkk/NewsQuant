"""news 를 현재 코드로 다시 돌려 news_reprocessed 에 쌓는다.

왜 필요한가 — 저장된 related_stocks 는 2026-09-12 에 고친 추출기(b75de2a)
이전의 출력이다. 같은 본문 4,000건에 구·신 코드를 각각 돌려 비교하면 기사
1,619건(40%)의 결과가 바뀐다. sentiment_score 도 구 로직이다. 그대로
백테스트하면 «이미 고친 버그가 섞인» 파이프라인을 측정하게 된다.

왜 별도 테이블인가 — 원본을 보존해야 재처리 로직이 또 바뀌었을 때 다시
만들 수 있고, DART 백필(6978b7c)처럼 운영 테이블을 또 건드리지 않아도 된다.

주의: reprocessing 의 timeliness_score 는 실운영의 값과 다르다. 신선도는 실행 시간
기준이지만, 실운영에서는 수집 직후 점수를 매겨 거의 상수(95.6%가 1.0)다. 오래된
기사를 다시 점수내면 ~0.2 이다. 원본을 복원하려면 감성분석기에 시계를 주입해야 하는데
이는 범위 밖이다. 그러나 timeliness 가 실운영에서 상수에 가까우므로 모든 행의
overall_score 를 거의 같은 양만큼 이동시키고, 백테스트가 측정하는 교차단면 순위는
바뀌지 않는다. 다만 이 테이블의 overall_score 를 절대값으로 실운영 임계값과
비교하면 안 된다.
"""
import logging
import subprocess
from typing import Dict, Optional

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

TABLE = "news_reprocessed"

_CREATE = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    news_id           TEXT PRIMARY KEY,
    published_at      TIMESTAMP NOT NULL,
    source            TEXT,
    title             TEXT,
    related_stocks    TEXT,
    sentiment_score   DOUBLE PRECISION,
    importance_score  DOUBLE PRECISION,
    impact_score      DOUBLE PRECISION,
    timeliness_score  DOUBLE PRECISION,
    overall_score     DOUBLE PRECISION,
    code_version      TEXT,
    reprocessed_at    TIMESTAMP NOT NULL DEFAULT now()
)
"""
_INDEX = f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_published ON {TABLE} (published_at)"


def code_version() -> str:
    """이 테이블은 «어느 시점 코드의 출력인가» 가 곧 의미다."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def ensure_table(db) -> None:
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE)
            cur.execute(_INDEX)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)


def _analyzers():
    from news_scraper.base_crawler import BaseCrawler
    from news_scraper.sentiment_analyzer import SentimentAnalyzer

    class _Extractor(BaseCrawler):
        def crawl_news_list(self, max_pages: int = 5):
            return []

        def crawl_news_detail(self, url: str):
            return None

    return _Extractor("reprocess"), SentimentAnalyzer()


def reprocess(db, apply: bool = False, limit: Optional[int] = None,
              only_news_id: Optional[str] = None) -> Dict:
    ensure_table(db)
    extractor, analyzer = _analyzers()
    version = code_version()

    conn = db.get_connection()
    written = 0
    try:
        with conn.cursor() as cur:
            # 건조 실행: count 만 한다 — 행 내용을 가져오지 않는다
            if not apply:
                if only_news_id:
                    cur.execute("SELECT count(*) FROM news WHERE news_id = %s",
                                (only_news_id,))
                    candidates = cur.fetchone()[0]
                else:
                    # limit 을 존중해서 후보를 센다 (LIMIT count(*) 는 no-op)
                    if limit:
                        cur.execute("SELECT count(*) FROM (SELECT 1 FROM news ORDER BY news_id LIMIT %s) t",
                                    (limit,))
                    else:
                        cur.execute("SELECT count(*) FROM news")
                    candidates = cur.fetchone()[0]
                conn.rollback()
            else:
                # 배치 처리 — 키셋 페이지네이션으로 진행을 저장한다
                batch_size = 5000
                last_news_id = "" if not only_news_id else None
                batch_num = 0
                total_rows = 0

                while True:
                    batch_num += 1
                    if only_news_id:
                        # 단일 행 모드
                        cur.execute("""SELECT news_id, title, content, published_at,
                                              source, category
                                       FROM news WHERE news_id = %s""",
                                    (only_news_id,))
                        rows = cur.fetchall()
                        if not rows:
                            break
                    else:
                        # 배치 모드 — 키셋 페이지네이션
                        cur.execute(f"""SELECT news_id, title, content, published_at,
                                               source, category
                                        FROM news
                                        WHERE news_id > %s
                                        ORDER BY news_id
                                        LIMIT %s""", (last_news_id, batch_size))
                        rows = cur.fetchall()
                        if not rows:
                            break

                    if limit and total_rows + len(rows) > limit:
                        rows = rows[:limit - total_rows]

                    for news_id, title, content, published_at, source, category in rows:
                        text = f"{title or ''} {content or ''}"
                        extracted_stocks = extractor.extract_stock_codes(text)

                        # 완전한 news dict 를 analyzer 에 준다 (published_at 은 ISO-8601 문자열)
                        pub_at_str = published_at.isoformat() if published_at else ""
                        scored = analyzer.analyze_news({
                            "title": title or "",
                            "content": content or "",
                            "source": source or "",
                            "category": category or "",
                            "related_stocks": extracted_stocks or "",
                            "published_at": pub_at_str
                        })

                        cur.execute(f"""
                            INSERT INTO {TABLE}
                              (news_id, published_at, source, title, related_stocks,
                               sentiment_score, importance_score, impact_score,
                               timeliness_score, overall_score, code_version, reprocessed_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                            ON CONFLICT (news_id) DO UPDATE SET
                               published_at = EXCLUDED.published_at,
                               source = EXCLUDED.source,
                               title = EXCLUDED.title,
                               related_stocks = EXCLUDED.related_stocks,
                               sentiment_score = EXCLUDED.sentiment_score,
                               importance_score = EXCLUDED.importance_score,
                               impact_score = EXCLUDED.impact_score,
                               timeliness_score = EXCLUDED.timeliness_score,
                               overall_score = EXCLUDED.overall_score,
                               code_version = EXCLUDED.code_version,
                               reprocessed_at = now()
                        """, (news_id, published_at, source, title, extracted_stocks,
                              scored.get("sentiment_score"), scored.get("importance_score"),
                              scored.get("impact_score"), scored.get("timeliness_score"),
                              scored.get("overall_score"), version))
                        written += 1
                        total_rows += 1

                    conn.commit()
                    if limit and total_rows >= limit:
                        break
                    if only_news_id:
                        break
                    if not rows:
                        break

                    last_news_id = rows[-1][0]
                    logger.info(f"배치 {batch_num}: 누적 {total_rows:,}건")

                candidates = total_rows
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)

    return {"candidates": candidates, "written": written, "applied": apply}
