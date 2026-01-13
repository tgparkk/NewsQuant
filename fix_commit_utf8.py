#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
커밋 메시지 UTF-8 인코딩 보장 스크립트
"""

import subprocess
import os
import sys
import io

# Windows 콘솔 인코딩 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def fix_commit_message():
    """커밋 메시지를 UTF-8로 보장하여 수정"""
    
    # 커밋 메시지 작성
    commit_msg = """한글 깨짐 원인 분석 문서 추가

- 네이버 금융 페이지는 실제로 EUC-KR 인코딩 사용 (메타 태그는 UTF-8로 표시)
- PowerShell의 cp949 인코딩과 Git의 UTF-8 불일치로 커밋 메시지 깨짐
- 원인 분석 스크립트 및 상세 문서 추가"""
    
    # UTF-8 파일로 저장 (BOM 없이)
    msg_file = os.path.join(os.getcwd(), 'commit_msg_utf8.txt')
    with open(msg_file, 'wb') as f:
        f.write(commit_msg.encode('utf-8'))
    
    print(f"커밋 메시지 파일 생성: {msg_file}")
    
    # Git commit --amend 실행
    # text=False로 설정하여 raw bytes 전달
    env = os.environ.copy()
    env['LANG'] = 'en_US.UTF-8'
    env['LC_ALL'] = 'en_US.UTF-8'
    
    try:
        # 절대 경로 사용
        abs_msg_file = os.path.abspath(msg_file)
        
        # Git 명령 실행
        result = subprocess.run(
            ['git', 'commit', '--amend', '-F', abs_msg_file],
            cwd=os.getcwd(),
            capture_output=True,
            text=False,  # 중요: raw bytes로 처리
            env=env
        )
        
        if result.returncode == 0:
                print("[OK] 커밋 메시지 수정 완료")
            
            # 확인: Git에서 직접 읽어서 확인
            verify_result = subprocess.run(
                ['git', 'log', '-1', '--pretty=format:%s', '--encoding=UTF-8'],
                cwd=os.getcwd(),
                capture_output=True,
                text=False
            )
            
            if verify_result.returncode == 0:
                decoded_msg = verify_result.stdout.decode('utf-8', errors='replace')
                print(f"\n저장된 커밋 메시지:")
                print(f"  {decoded_msg}")
                
                # 한글 확인
                has_korean = any('\uac00' <= char <= '\ud7a3' for char in decoded_msg)
                has_broken = '\ufffd' in decoded_msg or '?' in decoded_msg[:10]
                
                if has_korean and not has_broken:
                    print("\n[OK] 한글이 정상적으로 저장되었습니다!")
                else:
                    print("\n[WARN] 한글이 깨져있을 수 있습니다.")
            else:
                print("[WARN] 커밋 메시지 확인 실패")
        else:
            print(f"[ERR] 커밋 메시지 수정 실패:")
            print(result.stderr.decode('utf-8', errors='replace'))
            
    except Exception as e:
            print(f"[ERR] 오류 발생: {e}")
    finally:
        # 임시 파일 삭제
        if os.path.exists(msg_file):
            os.remove(msg_file)
            print(f"\n임시 파일 삭제: {msg_file}")

if __name__ == "__main__":
    fix_commit_message()











