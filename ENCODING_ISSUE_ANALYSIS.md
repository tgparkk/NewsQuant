# 한글 깨짐 원인 분석 리포트

## 1. 데이터베이스 저장 시 한글 깨짐 원인

### 근본 원인
**네이버 금융 페이지가 실제로는 EUC-KR 인코딩을 사용하지만, HTML 메타 태그에는 UTF-8로 표시되어 있음**

### 상세 분석

#### 네이버 금융 페이지 실제 인코딩
```
Content-Type 헤더: text/html;charset=EUC-KR
Response 인코딩: EUC-KR
Response apparent_encoding: EUC-KR
```

#### HTML 메타 태그 (잘못된 정보)
```html
<meta charset="utf-8">  <!-- 실제로는 EUC-KR인데 UTF-8로 표시 -->
```

#### 이전 코드의 문제점
1. **UTF-8로 먼저 디코딩 시도**
   ```python
   # 이전 코드
   response.encoding = 'utf-8'  # 잘못된 가정
   html_content = response.text  # UTF-8로 디코딩 시도 → 실패
   ```
   - 결과: `UnicodeDecodeError` 또는 replacement character(`\ufffd`) 생성

2. **자동 인코딩 추정 실패**
   - `response.text`는 `response.encoding`을 기반으로 디코딩
   - 잘못된 인코딩 설정 시 깨진 문자로 저장됨

#### 현재 해결 방법
```python
# 여러 인코딩 순차 시도
encodings_to_try = ['utf-8', 'euc-kr', 'cp949', 'latin1']
for encoding in encodings_to_try:
    try:
        html_content = response.content.decode(encoding, errors='strict')
        if any('\uac00' <= char <= '\ud7a3' for char in html_content[:1000]):
            break  # 한글이 정상적으로 디코딩되면 성공
    except UnicodeDecodeError:
        continue
```

### 테스트 결과
- **UTF-8 디코딩**: ❌ 실패 (`'utf-8' codec can't decode byte 0xb3`)
- **EUC-KR 디코딩**: ✓ 성공 (한글 정상: "네이버페이")
- **CP949 디코딩**: ✓ 성공 (EUC-KR과 호환)

---

## 2. 커밋 메시지 한글 깨짐 원인

### 근본 원인
**PowerShell의 기본 인코딩(cp949)과 Git의 인코딩 처리 불일치**

### 상세 분석

#### 시스템 인코딩
```
Python 기본 인코딩: utf-8
stdout 인코딩: utf-8 (Python 스크립트 실행 시)
PowerShell 기본 인코딩: cp949 (코드 페이지 949)
로케일 기본 인코딩: cp949
```

#### 문제 발생 과정
1. **PowerShell에서 `git commit -m "한글"` 실행**
   ```powershell
   git commit -m "개선: 데이터 수집"
   ```
   - PowerShell이 "한글"을 cp949로 인코딩하여 Git에 전달
   - Git이 이를 UTF-8로 해석하려고 시도
   - 결과: 바이트 시퀀스 불일치로 깨짐

2. **Git 설정 확인**
   ```
   i18n.commitencoding=utf-8
   i18n.logoutputencoding=utf-8
   ```
   - Git은 UTF-8로 저장하려고 하지만, 입력이 cp949로 들어옴

#### 해결 방법
**UTF-8 파일로 커밋 메시지 작성 후 사용**
```python
# Python 스크립트로 UTF-8 파일 생성
with open('commit_msg.txt', 'wb') as f:
    f.write("개선: 데이터 수집\n".encode('utf-8'))

# Git에서 파일 사용
git commit --amend --file commit_msg.txt
```

---

## 3. 데이터베이스 저장 시 추가 보호 로직

### 현재 구현
```python
def ensure_utf8(text):
    """문자열이 올바른 UTF-8인지 확인하고 정리"""
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='replace')
    # replacement character 제거
    if '\ufffd' in text:
        text = text.replace('\ufffd', '')
    return text
```

### 효과
- 바이트 데이터가 들어와도 UTF-8로 변환
- 이미 깨진 문자(replacement character) 제거
- 데이터베이스에 저장 전 최종 검증

---

## 4. 종합 원인 요약

### 데이터 깨짐
1. **네이버 금융 페이지**: EUC-KR 인코딩 사용 (메타 태그는 UTF-8로 표시)
2. **이전 코드**: UTF-8로 먼저 디코딩 시도 → 실패
3. **결과**: 깨진 바이트가 replacement character로 저장됨

### 커밋 메시지 깨짐
1. **PowerShell**: cp949 인코딩 사용
2. **Git**: UTF-8로 저장 시도
3. **결과**: 인코딩 불일치로 깨짐

### 해결 상태
- ✅ 크롤러: 여러 인코딩 순차 시도 (EUC-KR 성공)
- ✅ 데이터베이스: 저장 전 UTF-8 보장 로직 추가
- ✅ 커밋 메시지: UTF-8 파일로 작성 후 사용

---

## 5. 권장 사항

### 앞으로 커밋 메시지 작성 시
```bash
# 방법 1: Python 스크립트 사용 (권장)
python -c "open('msg.txt','wb').write('한글 메시지\n'.encode('utf-8'))"
git commit -F msg.txt

# 방법 2: Git Bash 사용
# Git Bash는 UTF-8을 기본으로 사용하므로 한글이 정상 작동
```

### 크롤러 인코딩 처리
- 항상 여러 인코딩을 순차 시도
- 한글 디코딩 성공 여부 검증
- 데이터베이스 저장 전 최종 검증












