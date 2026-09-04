# -*- coding: utf-8 -*-
"""관리자 비밀번호 초기화 스크립트.

실행: python reset_admin.py
실행 후 /admin 에 접속하면 처음처럼 비밀번호 설정 화면이 나온다.
재고·신청 등 다른 데이터는 그대로 유지된다.
"""
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pawnshop.db")

if not os.path.isfile(DB_PATH):
    print("아직 DB가 없습니다. 서버를 한 번 실행한 뒤 사용하세요.")
else:
    c = sqlite3.connect(DB_PATH)
    c.execute("DELETE FROM settings WHERE key IN (?,?)", ("admin_pw", "admin_salt"))
    c.commit()
    print("초기화 완료! /admin 에 접속해서 새 비밀번호를 설정하세요.")
