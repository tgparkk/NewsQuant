"""news 를 현재 코드로 다시 돌려 news_reprocessed 에 쌓는다.

왜 필요한가 — 저장된 related_stocks 는 2026-09-12 에 고친 추출기(b75de2a)
이전의 출력이다. 같은 본문 4,000건에 구·신 코드를 각각 돌려 비교하면 기사
1,619건(40%)의 결과가 바뀐다. sentiment_score 도 구 로직이다. 그대로
백테스트하면 «이미 고친 버그가 섞인» 파이프라인을 측정하게 된다.

왜 별도 테이블인가 — 원본을 보존해야 재처리 로직이 또 바뀌었을 때 다시
만들 수 있고, DART 백필(6978b7c)처럼 운영 테이블을 또 건드리지 않아도 된다.
"""
import logging
import subprocess
from typing import Dict, Optional

logger = logging.getLogger(__name__)

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

    where = "WHERE news_id = %s" if only_news_id else ""
    params = (only_news_id,) if only_news_id else ()
    tail = f" LIMIT {int(limit)}" if limit else ""

    conn = db.get_connection()
    written = 0
    try:
        with conn.cursor() as cur:
            cur.execute(f"""SELECT news_id, title, content, published_at, source
                            FROM news {where} ORDER BY news_id{tail}""", params)
            rows = cur.fetchall()
            candidates = len(rows)

            if apply:
                for news_id, title, content, published_at, source in rows:
                    text = f"{title or ''} {content or ''}"
                    scored = analyzer.analyze_news({"title": title or "",
                                                    "content": content or ""})
                    cur.execute(f"""
                        INSERT INTO {TABLE}
                          (news_id, published_at, source, title, related_stocks,
                           sentiment_score, importance_score, impact_score,
                           timeliness_score, overall_score, code_version, reprocessed_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                        ON CONFLICT (news_id) DO UPDATE SET
                           published_at = EXCLUDED.published_at,
                           related_stocks = EXCLUDED.related_stocks,
                           sentiment_score = EXCLUDED.sentiment_score,
                           importance_score = EXCLUDED.importance_score,
                           impact_score = EXCLUDED.impact_score,
                           timeliness_score = EXCLUDED.timeliness_score,
                           overall_score = EXCLUDED.overall_score,
                           code_version = EXCLUDED.code_version,
                           reprocessed_at = now()
                    """, (news_id, published_at, source, title,
                          extractor.extract_stock_codes(text),
                          scored.get("sentiment_score"), scored.get("importance_score"),
                          scored.get("impact_score"), scored.get("timeliness_score"),
                          scored.get("overall_score"), version))
                    written += 1
        if apply:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        db._put_connection(conn)

    return {"candidates": candidates, "written": written, "applied": apply}
