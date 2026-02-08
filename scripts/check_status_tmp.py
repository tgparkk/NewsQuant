import sqlite3
from datetime import datetime

def check_status():
    conn = sqlite3.connect('news_data.db')
    cursor = conn.cursor()
    
    print("=== Today's Collection Log (2026-01-08) ===")
    cursor.execute("""
        SELECT source, news_count, status, error_message, collected_at 
        FROM collection_log 
        WHERE collected_at >= '2026-01-08' 
        ORDER BY collected_at DESC
    """)
    rows = cursor.fetchall()
    for row in rows:
        print(f"Source: {row[0]}, Count: {row[1]}, Status: {row[2]}, Error: {row[3]}, Time: {row[4]}")
    
    print("\n=== Recent DART Entries ===")
    cursor.execute("""
        SELECT title, published_at, created_at 
        FROM news 
        WHERE source = 'dart' 
        ORDER BY created_at DESC 
        LIMIT 5
    """)
    rows = cursor.fetchall()
    for row in rows:
        print(f"Title: {row[0]}, Published: {row[1]}, Created: {row[2]}")
    
    conn.close()

if __name__ == "__main__":
    check_status()

