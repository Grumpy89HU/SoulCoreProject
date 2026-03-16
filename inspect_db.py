import sqlite3
import json

def inspect_all():
    db_path = "soulcore.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Összes tábla lekérése
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']

    print(f"=== SOULCORE ADATBÁZIS STRUKTÚRA ÉS TARTALOM ===")
    print(f"Adatbázis fájl: {db_path}\n")

    for table in tables:
        print(f"\n--- TÁBLA: {table} ---")
        
        # Szerkezet (Oszlopok)
        cursor.execute(f"PRAGMA table_info({table})")
        cols = cursor.fetchall()
        col_names = [c[1] for c in cols]
        print(f"Oszlopok: {', '.join(col_names)}")
        print("-" * 50)

        # Adatok
        cursor.execute(f"SELECT * FROM {table} LIMIT 50") # Limit, hogy ne legyen túl hosszú
        rows = cursor.fetchall()
        
        if not rows:
            print("[ÜRES TÁBLA]")
        else:
            for row in rows:
                # Szebb megjelenítés: oszlopnév -> érték
                row_dict = dict(zip(col_names, row))
                print(json.dumps(row_dict, indent=2, ensure_ascii=False))
                print("." * 20)

    conn.close()

if __name__ == "__main__":
    inspect_all()
