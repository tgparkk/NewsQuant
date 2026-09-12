"""DB 의 `stock_info` 로 종목명→종목코드 사전을 만든다.

구 생성기(`fetch_stock_list_naver.py`)는 네이버 금융을 긁으면서 접미사를 잘라
별칭을 파생시켰고, 그 별칭이 다른 회사를 덮어써 골프존(215000)·F&F(383220)·
컴투스(078340)·대상(001680) 이 사전에서 사라졌다. 여기서는 `stock_info` 의
이름을 «그대로» 옮기기만 한다 — 별칭을 만들지 않는 것이 이 모듈의 요점이다.

산출물은 지금까지처럼 커밋되는 정적 파일(`stock_codes_extended.py`)이다.
`base_crawler` 가 import 시점에 DB 를 타지 않아야 오프라인 실행·테스트·
백테스트 재현성이 유지된다.
"""
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def build_dict(rows: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    """(종목명, 종목코드) 행들을 사전으로 옮긴다.

    버리는 것: 6자리 숫자가 아닌 코드, 두 글자 미만 이름(추출기가 어차피
    건너뛴다). 같은 이름이 두 번 오면 먼저 온 쪽을 남긴다 — 조용히 덮어쓰는
    것이 바로 구 생성기가 낸 사고다.
    """
    mapping: Dict[str, str] = {}
    for raw_name, raw_code in rows:
        name = (raw_name or "").strip()
        code = (raw_code or "").strip()
        if len(code) != 6 or not code.isdigit():
            continue
        if len(name) < 2:
            continue
        mapping.setdefault(name, code)
    return mapping


_HEADER = '''"""자동 생성 파일 — 손으로 고치지 마라.

출처: {source}
생성: scripts/build_stock_dict.py

종목 {count}개. 이름은 stock_info 에 있는 그대로이며 별칭은 만들지 않는다.
뉴스에서 실제로 쓰이는 통칭('네이버', '삼전', '포스코')은 손으로 검수한
news_scraper/base_crawler.py 의 STOCK_NAME_TO_CODE_BASE 가 담당한다.
"""

EXTENDED_STOCK_CODES = {{
'''


def render_module(mapping: Dict[str, str], source: str) -> str:
    """사전을 커밋 가능한 파이썬 모듈 텍스트로 만든다.

    이름순으로 정렬한다 — 재생성할 때마다 순서가 흔들리면 diff 를 읽을 수 없다.
    """
    lines = [_HEADER.format(source=source, count=len(mapping))]
    for name in sorted(mapping):
        lines.append(f"    {name!r}: {mapping[name]!r},\n")
    lines.append("}\n")
    return "".join(lines)


def load_stock_info_rows(db) -> List[Tuple[str, str]]:
    """stock_info 에서 (종목명, 종목코드) 를 읽는다.

    이름순으로 고정해 재생성 결과가 실행마다 흔들리지 않게 한다.
    """
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT stock_name, stock_code FROM stock_info ORDER BY stock_name"
            )
            return list(cur.fetchall())
    finally:
        conn.rollback()
        db._put_connection(conn)


OUTPUT = Path(__file__).resolve().parent.parent / "stock_codes_extended.py"


def main() -> int:
    # `python scripts/build_stock_dict.py` 로도 돌 수 있게 리포 루트를 얹는다.
    import sys
    sys.path.insert(0, str(OUTPUT.parent))
    from news_scraper.database import NewsDatabase

    db = NewsDatabase()
    rows = load_stock_info_rows(db)
    mapping = build_dict(rows)
    if not mapping:
        print("stock_info 에서 아무것도 읽지 못했다 — 쓰지 않는다.")
        return 1

    snapshot = _snapshot_date(db)
    text = render_module(mapping, source=f"stock_info@{snapshot}")
    OUTPUT.write_text(text, encoding="utf-8")

    print(f"{OUTPUT.name}: {len(mapping)}개 종목 (stock_info@{snapshot}, 원본 {len(rows)}행)")
    return 0


def _snapshot_date(db) -> str:
    """stock_info 가 언제 갱신된 표인지 — 산출물에 남길 출처 표기."""
    conn = db.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT max(updated_at)::date FROM stock_info")
            value = cur.fetchone()[0]
    finally:
        conn.rollback()
        db._put_connection(conn)
    return str(value) if value else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
