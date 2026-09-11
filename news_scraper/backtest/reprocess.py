"""news 를 현재 코드로 다시 돌려 news_reprocessed 에 쌓는다.

왜 필요한가 — 저장된 related_stocks 는 2026-09-12 에 고친 추출기(b75de2a)
이전의 출력이다. 같은 본문 4,000건에 구·신 코드를 각각 돌려 비교하면 기사
1,619건(40%)의 결과가 바뀐다. sentiment_score 도 구 로직이다. 그대로
백테스트하면 «이미 고친 버그가 섞인» 파이프라인을 측정하게 된다.

왜 별도 테이블인가 — 원본을 보존해야 재처리 로직이 또 바뀌었을 때 다시
만들 수 있고, DART 백필(6978b7c)처럼 운영 테이블을 또 건드리지 않아도 된다.

주의: reprocessing 의 timeliness_score 는 실운영의 값과 다르다.
- 실운영: 기사를 수집 직후 점수를 매겨 24시간 내 = 1.0 (201,889/211,197 = 95.6%의 행);
  나머지 일부만 0.5(≤48h), 0.2(≤1주), 또는 0.1(>1주);
- reprocessing: 수개월 뒤에 돌려 대부분 >1주 = 0.1 (측정값 avg 0.106).
timeliness 는 실운영에서 거의 상수(1.0)이므로, 이 차이는 모든 행의 overall_score 를
거의 같은 양만큼 이동시키고, 백테스트가 측정하는 교차단면 순위는 바뀌지 않는다.
다만 이 테이블의 overall_score 를 절대값으로 실운영 임계값과 비교하면 안 된다.
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


def _load_stock_info_map(db) -> Dict[str, str]:
    """stock_info 를 정규화된 이름→코드 dict 로 로드한다.

    DART API 의 stock_code 필드는 저장된 텍스트로 재유도할 수 없다. stock_info 는
    이를 재현한다는 증거: 99.6% 정확도로 실운영의 저장값과 일치한다.
    공백을 제거해 정규화(효성 ITX → 효성ITX) 하므로 title/content 의 형식 차이를
    흡수한다.
    """
    stock_map = {}
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT stock_code, stock_name FROM stock_info")
            for code, name in cur.fetchall():
                if name:
                    normalized = name.replace(" ", "").replace("\t", "")
                    stock_map[normalized] = code
    finally:
        conn.rollback()
        db._put_connection(conn)
    return stock_map


def _resolve_dart_company(title: str, content: str, stock_map: Dict[str, str]) -> Optional[str]:
    """DART 행에서 stock_info 를 이용해 회사명을 코드로 변환한다.

    선호 순서:
    1. content 의 '기업명: <name>' 줄 (가장 깨끗함)
    2. title 의 '[<name>]' 접두어
    3. 찾지 못하면 None (문자 추출로 폴백)
    """
    # content 에서 기업명 추출
    if content:
        for line in content.split('\n'):
            if line.startswith('기업명:'):
                company = line.replace('기업명:', '').strip()
                if company:
                    normalized = company.replace(" ", "").replace("\t", "")
                    if normalized in stock_map:
                        return stock_map[normalized]

    # title 에서 [회사명] 추출
    if title and title.startswith('['):
        end = title.find(']')
        if end > 0:
            company = title[1:end].strip()
            if company:
                normalized = company.replace(" ", "").replace("\t", "")
                if normalized in stock_map:
                    return stock_map[normalized]

    return None


def reprocess(db, apply: bool = False, limit: Optional[int] = None,
              only_news_id: Optional[str] = None) -> Dict:
    ensure_table(db)
    extractor, analyzer = _analyzers()
    version = code_version()

    # DART 행을 위해 stock_info 맵을 미리 로드한다
    stock_map = _load_stock_info_map(db)

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
                        # DART 행은 회사명으로 코드를 복원한다 (API 의 stock_code 필드 재현)
                        if source == 'dart':
                            dart_code = _resolve_dart_company(title or "", content or "", stock_map)
                            extracted_stocks = dart_code if dart_code else extractor.extract_stock_codes(f"{title or ''} {content or ''}")
                        else:
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
